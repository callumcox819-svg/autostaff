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
from services.mailing_deliverability import (
    burst_single_proxy_wave_gap_sec,
    burst_wave_gap_sec,
    inbox_stagger_ms,
    log_deliverability_profile,
    mailing_fast_mode,
    mailing_max_per_account_hour,
)
from services.mailing_rotation import (
    last_sent_ts_by_account,
    order_accounts_for_burst,
    pair_targets_with_accounts,
    sent_count_last_hour_by_account,
)
from services.mailing_send import send_mailing_one_parallel
from services.residential_proxy import (
    is_residential_gateway,
    residential_burst_inflight,
    residential_smtp_timeout_sec,
)
from services.sender import normalize_send_error
from services.smtp_proxy_send import (
    MAIL_FAST_SMTP_TIMEOUT_SEC,
    pick_sticky_proxy_for_fast_mailing,
)
from services.mailing_send import MAIL_FAST_SEND_RETRIES

logger = logging.getLogger(__name__)

BURST_SMTP_RETRIES = max(1, min(4, int(os.getenv("BURST_SMTP_RETRIES", "1"))))
BURST_RETRY_PAUSE_SEC = max(
    0.0, min(1.0, float(os.getenv("BURST_RETRY_PAUSE_SEC", "0.06")))
)
BURST_MAX_INFLIGHT = max(
    4, min(120, int(os.getenv("BURST_MAX_INFLIGHT", "40")))
)
# Один sticky-прокси + много Gmail: параллель по ящикам (как в быстрых мейлерах).
# DB-сессия на SMTP больше не держится — пул свободен для /start при волне 40.
BURST_SINGLE_PROXY_INFLIGHT = max(
    8, min(80, int(os.getenv("BURST_SINGLE_PROXY_INFLIGHT", "40")))
)


def burst_per_letter_timeout_sec(sticky_proxy=None, *, num_proxies: int = 1) -> int:
    """Потолок на письмо с учётом reconnect sticky-прокси (EOF → новый IP)."""
    raw_env = (os.getenv("BURST_PER_LETTER_TIMEOUT_SEC") or "").strip()
    if raw_env.isdigit():
        return max(8, min(240, int(raw_env)))

    from services.smtp_proxy_send import (
        MAIL_STICKY_PROXY_RECONNECTS,
        MAIL_STICKY_PROXY_RECONNECT_PAUSE_SEC,
    )

    smtp_t = int(MAIL_FAST_SMTP_TIMEOUT_SEC)
    if int(num_proxies) <= 1:
        smtp_t = max(
            smtp_t,
            min(35, int(os.getenv("BURST_SINGLE_PROXY_SMTP_TIMEOUT_SEC", "25"))),
        )
    else:
        cap_fast = int(os.getenv("BURST_FAST_SMTP_TIMEOUT_CAP_SEC", "15"))
        smtp_t = min(smtp_t, cap_fast)

    if sticky_proxy is not None and is_residential_gateway(sticky_proxy):
        boosted = int(residential_smtp_timeout_sec())
        smtp_t = max(smtp_t, min(40, boosted))

    reconnects = MAIL_STICKY_PROXY_RECONNECTS if int(num_proxies) <= 1 else 1
    pause = MAIL_STICKY_PROXY_RECONNECT_PAUSE_SEC * max(0, reconnects - 1)
    # smtp×попытки + паузы + небольшой запас (без x MAIL_FAST_SEND_RETRIES)
    return max(15, min(100, int(smtp_t * reconnects + pause + 5)))


def burst_wave_size_for_proxy(
    proxy, num_accounts: int, *, num_proxies: int = 1
) -> int:
    cap = BURST_MAX_INFLIGHT
    if int(num_proxies) <= 1:
        cap = min(cap, BURST_SINGLE_PROXY_INFLIGHT)
    if is_residential_gateway(proxy):
        # Residential тоже можно гнать по числу ящиков, но с потолком env.
        cap = min(cap, max(residential_burst_inflight(), BURST_SINGLE_PROXY_INFLIGHT // 2))
    return max(1, min(int(num_accounts), cap))


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
    per_letter_timeout_sec: int,
) -> Tuple[bool, str, str]:
    last_err = ""
    last_msgid = ""
    for attempt in range(1, BURST_SMTP_RETRIES + 1):
        try:
            # Не держим db_session на время SMTP — иначе пул (15+25) и /start умирают.
            ok, err, msgid = await asyncio.wait_for(
                send_mailing_one_parallel(
                    None,
                    db_user_id,
                    account,
                    to_email,
                    subject,
                    body,
                    sender_name=sender_name,
                    sticky_proxy_id=sticky_proxy_id,
                ),
                timeout=float(per_letter_timeout_sec),
            )
            if ok:
                return True, "", (msgid or "")
            last_err = normalize_send_error(err)
            last_msgid = msgid or ""
        except asyncio.TimeoutError:
            last_err = normalize_send_error(
                f"SMTP_TIMEOUT|timeout|exceeded {per_letter_timeout_sec}s"
            )
        except Exception as ex:
            last_err = normalize_send_error(str(ex))

        if attempt < BURST_SMTP_RETRIES and BURST_RETRY_PAUSE_SEC > 0:
            await asyncio.sleep(BURST_RETRY_PAUSE_SEC)
    return False, last_err or "UNKNOWN", last_msgid


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
    on_success: Callable[..., Awaitable[None]],
    on_failure: Callable[[OfferEmail, str, EmailAccount], Awaitable[bool]],
    start_delay_sec: float = 0.0,
    per_letter_timeout_sec: int = 90,
    hour_counts: dict[str, int] | None = None,
    hour_cap: int = 0,
    hour_lock: asyncio.Lock | None = None,
) -> Tuple[int, int]:
    if start_delay_sec > 0:
        await asyncio.sleep(start_delay_sec)

    em = (account.email or "").strip().lower()
    if hour_cap > 0 and hour_counts is not None and em:
        lock = hour_lock or asyncio.Lock()
        async with lock:
            if int(hour_counts.get(em, 0)) >= hour_cap:
                await on_failure(
                    tgt,
                    f"ACCOUNT_SOFT_CAP|limit|{hour_cap}/hour",
                    account,
                )
                return 0, 1

    try:
        async with db_session() as session:
            subject, body = await build_message(session, tgt)
        to_addr = (tgt.email or "").strip()
        ok, err, msgid = await _send_one_with_retry(
            db_user_id=db_user_id,
            account=account,
            to_email=to_addr,
            subject=subject,
            body=body,
            sender_name=sender_name,
            sticky_proxy_id=sticky_proxy_id,
            per_letter_timeout_sec=per_letter_timeout_sec,
        )
        if ok:
            if hour_counts is not None and em:
                lock = hour_lock or asyncio.Lock()
                async with lock:
                    hour_counts[em] = int(hour_counts.get(em, 0)) + 1
            await on_success(tgt, subject, (account.email or "").strip(), msgid or "", body)
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
    on_success: Callable[..., Awaitable[None]],
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
        hour_counts = await sent_count_last_hour_by_account(session, int(db_user_id))
        from services.smtp_proxy_send import _list_active_mailing_proxies

        n_proxies = len(await _list_active_mailing_proxies(session, int(db_user_id)))
        if sticky_px is not None:
            try:
                session.expunge(sticky_px)
            except Exception:
                pass
    if not sticky_px:
        raise RuntimeError("NO_ROTATING_PROXY")

    log_deliverability_profile(logger)

    hour_cap = mailing_max_per_account_hour()
    hour_lock = asyncio.Lock()

    sticky_proxy_id = int(sticky_px.id)
    acc_ordered = order_accounts_for_burst(list(accounts), last_sent=last_sent)
    if hour_cap > 0:
        eligible = [
            a
            for a in acc_ordered
            if int(hour_counts.get((a.email or "").strip().lower(), 0)) < hour_cap
        ]
        if eligible:
            skipped = len(acc_ordered) - len(eligible)
            if skipped:
                logger.info(
                    "soft cap %s/h: skip %s accounts already at limit",
                    hour_cap,
                    skipped,
                )
            acc_ordered = eligible
        else:
            logger.warning(
                "soft cap %s/h: all accounts at limit — sending anyway with first wave only",
                hour_cap,
            )
    per_letter_tmo = burst_per_letter_timeout_sec(sticky_px, num_proxies=n_proxies or 1)
    wave_size = burst_wave_size_for_proxy(
        sticky_px, len(acc_ordered), num_proxies=n_proxies or 1
    )
    if (n_proxies or 1) <= 1:
        logger.info(
            "single proxy burst: wave=%s letter_tmo=%ss accounts=%s (parallel by mailbox)",
            wave_size,
            per_letter_tmo,
            len(acc_ordered),
        )
    if is_residential_gateway(sticky_px):
        logger.info(
            "residential proxy %s:%s — wave=%s letter_cap=%ss",
            sticky_px.host,
            sticky_px.port,
            wave_size,
            per_letter_tmo,
        )
    pairs = pair_targets_with_accounts(targets, acc_ordered)
    waves = split_into_waves(pairs, wave_size=wave_size)
    est_wave = min(float(per_letter_tmo) * 0.05, 4.0)
    wave_gap = burst_wave_gap_sec(len(waves), estimated_wave_sec=est_wave)
    # Один sticky-прокси + большая волна: в inbox не схлопывать паузу; в fast — старый потолок.
    if (n_proxies or 1) <= 1 and wave_size >= 12:
        single_gap = burst_single_proxy_wave_gap_sec()
        if mailing_fast_mode():
            wave_gap = min(wave_gap, single_gap)
        else:
            wave_gap = max(wave_gap, single_gap)
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
                    per_letter_timeout_sec=per_letter_tmo,
                    hour_counts=hour_counts,
                    hour_cap=hour_cap,
                    hour_lock=hour_lock,
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
