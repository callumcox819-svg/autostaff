"""Burst-рассылка: волны параллельно по ящикам, 2–10 с на очередь + inbox-safe."""

from __future__ import annotations

import asyncio
import logging
import os
import random
import time
from typing import Awaitable, Callable, List, Sequence, Tuple

from sqlalchemy.ext.asyncio import AsyncSession

from database import db_session
from models import EmailAccount, OfferEmail
from services.mailing_deliverability import burst_wave_gap_sec, inbox_stagger_ms, log_deliverability_profile
from services.mailing_rotation import (
    last_sent_ts_by_account,
    order_accounts_for_burst,
    pair_targets_with_accounts,
)
from services.mailing_send import send_mailing_one_parallel
from services.sender import normalize_send_error
from services.smtp_proxy_send import pick_sticky_proxy_for_fast_mailing

logger = logging.getLogger(__name__)

BURST_SMTP_RETRIES = max(1, min(4, int(os.getenv("BURST_SMTP_RETRIES", "2"))))
BURST_RETRY_PAUSE_SEC = max(
    0.0, min(1.0, float(os.getenv("BURST_RETRY_PAUSE_SEC", "0.06")))
)
BURST_PER_LETTER_TIMEOUT_SEC = max(
    12, min(60, int(os.getenv("BURST_PER_LETTER_TIMEOUT_SEC", "24")))
)
BURST_MAX_INFLIGHT = max(
    4, min(120, int(os.getenv("BURST_MAX_INFLIGHT", "36")))
)


def shuffle_accounts(accounts: Sequence[EmailAccount]) -> List[EmailAccount]:
    """Совместимость: случайный порядок (prefer order_accounts_for_burst)."""
    out = list(accounts)
    random.shuffle(out)
    return out


def split_into_waves(
    pairs: Sequence[Tuple[OfferEmail, EmailAccount]],
    *,
    wave_size: int,
) -> List[List[Tuple[OfferEmail, EmailAccount]]]:
    size = max(1, wave_size)
    return [list(pairs[i : i + size]) for i in range(0, len(pairs), size)]


async def _send_one_with_retry(
    *,
    db_user_id: int,
    account: EmailAccount,
    to_email: str,
    subject: str,
    body: str,
    sender_name: str | None,
    sticky_proxy_id: int,
) -> Tuple[bool, str]:
    last_err = ""
    for attempt in range(1, BURST_SMTP_RETRIES + 1):
        try:
            async with db_session() as session:
                ok, err, _ = await asyncio.wait_for(
                    send_mailing_one_parallel(
                        session,
                        db_user_id,
                        account,
                        to_email,
                        subject,
                        body,
                        sender_name=sender_name,
                        sticky_proxy_id=sticky_proxy_id,
                    ),
                    timeout=BURST_PER_LETTER_TIMEOUT_SEC,
                )
            if ok:
                return True, ""
            last_err = normalize_send_error(err)
        except asyncio.TimeoutError:
            last_err = normalize_send_error(
                f"SMTP_TIMEOUT|timeout|exceeded {BURST_PER_LETTER_TIMEOUT_SEC}s"
            )
        except Exception as ex:
            last_err = normalize_send_error(str(ex))

        if attempt < BURST_SMTP_RETRIES and BURST_RETRY_PAUSE_SEC > 0:
            await asyncio.sleep(BURST_RETRY_PAUSE_SEC)
    return False, last_err or "UNKNOWN"


async def _send_pair(
    *,
    db_user_id: int,
    tgt: OfferEmail,
    account: EmailAccount,
    sticky_proxy_id: int,
    sender_name: str | None,
    build_message: Callable[
        [AsyncSession, OfferEmail], Awaitable[Tuple[str, str]]
    ],
    on_success: Callable[[OfferEmail, str, str], Awaitable[None]],
    on_failure: Callable[[OfferEmail, str, EmailAccount], Awaitable[bool]],
    start_delay_sec: float = 0.0,
) -> Tuple[int, int]:
    if start_delay_sec > 0:
        await asyncio.sleep(start_delay_sec)

    try:
        async with db_session() as session:
            subject, body = await build_message(session, tgt)
        to_addr = (tgt.email or "").strip()
        ok, err = await _send_one_with_retry(
            db_user_id=db_user_id,
            account=account,
            to_email=to_addr,
            subject=subject,
            body=body,
            sender_name=sender_name,
            sticky_proxy_id=sticky_proxy_id,
        )
        if ok:
            await on_success(tgt, subject, (account.email or "").strip())
            return 1, 0
        await on_failure(tgt, err, account)
        return 0, 1
    except Exception as ex:
        logger.exception(
            "burst send_pair failed tg_target=%s acc=%s",
            getattr(tgt, "id", None),
            getattr(account, "email", None),
        )
        try:
            await on_failure(tgt, normalize_send_error(str(ex)), account)
        except Exception:
            pass
        return 0, 1


def _should_continue_burst(tg_user_id: int) -> bool:
    """Между волнами — только явная остановка пользователем (не is_running)."""
    try:
        from services.sending_state import get_sending_state

        st = get_sending_state(tg_user_id)
        if st is None:
            return True
        return not bool(st.is_stopping)
    except Exception:
        return True


async def run_burst_mailing(
    *,
    db_user_id: int,
    tg_user_id: int,
    accounts: Sequence[EmailAccount],
    targets: Sequence[OfferEmail],
    sender_name: str | None,
    build_message: Callable[
        [AsyncSession, OfferEmail], Awaitable[Tuple[str, str]]
    ],
    on_success: Callable[[OfferEmail, str, str], Awaitable[None]],
    on_failure: Callable[[OfferEmail, str, EmailAccount], Awaitable[bool]],
) -> Tuple[int, int, int | None, float]:
    """
    Волны: в каждой волне до N параллельных SMTP (N = число ящиков),
    микро-stagger старта + короткая пауза между волнами (inbox-safe).
    """
    if not targets or not accounts:
        return 0, 0, None, 0.0

    async with db_session() as session:
        sticky_px = await pick_sticky_proxy_for_fast_mailing(session, int(db_user_id))
        last_sent = await last_sent_ts_by_account(session, int(db_user_id))
    if not sticky_px:
        raise RuntimeError("NO_ROTATING_PROXY")

    log_deliverability_profile(logger)

    sticky_proxy_id = int(sticky_px.id)
    acc_ordered = order_accounts_for_burst(list(accounts), last_sent=last_sent)
    pairs = pair_targets_with_accounts(targets, acc_ordered)
    wave_size = max(1, min(len(acc_ordered), BURST_MAX_INFLIGHT))
    waves = split_into_waves(pairs, wave_size=wave_size)
    est_wave = min(
        float(BURST_PER_LETTER_TIMEOUT_SEC) * 0.45,
        8.0,
    )
    wave_gap = burst_wave_gap_sec(len(waves), estimated_wave_sec=est_wave)
    stagger_s = inbox_stagger_ms() / 1000.0

    sent = failed = 0
    t0 = time.perf_counter()
    for wave_idx, wave in enumerate(waves):
        if not _should_continue_burst(tg_user_id):
            break
        if wave_idx > 0 and wave_gap > 0:
            await asyncio.sleep(wave_gap + random.uniform(0, wave_gap * 0.2))

        results = await asyncio.gather(
            *[
                _send_pair(
                    db_user_id=db_user_id,
                    tgt=tgt,
                    account=acc,
                    sticky_proxy_id=sticky_proxy_id,
                    sender_name=sender_name,
                    build_message=build_message,
                    on_success=on_success,
                    on_failure=on_failure,
                    start_delay_sec=(stagger_s * j) + random.uniform(0, stagger_s * 0.25),
                )
                for j, (tgt, acc) in enumerate(wave)
            ],
            return_exceptions=True,
        )
        for r in results:
            if isinstance(r, BaseException):
                logger.exception("burst wave task failed: %s", r)
                failed += 1
                continue
            s, f = r
            sent += int(s)
            failed += int(f)

    elapsed = time.perf_counter() - t0
    logger.info(
        "[burst wave] tg=%s sent=%s failed=%s targets=%s accounts=%s waves=%s "
        "proxy=%s stagger_ms=%s wave_gap=%.2fs elapsed=%.2fs",
        tg_user_id,
        sent,
        failed,
        len(targets),
        wave_size,
        len(waves),
        sticky_proxy_id,
        inbox_stagger_ms(),
        wave_gap,
        elapsed,
    )
    return sent, failed, sticky_proxy_id, elapsed
