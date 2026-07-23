"""GAG burst: быстро, но с inbox-safe паттерном (stagger + gap на ящик)."""

from __future__ import annotations

import asyncio
import logging
import os
import random
import time
from collections import defaultdict
from typing import Awaitable, Callable, List, Sequence, Tuple

from sqlalchemy.ext.asyncio import AsyncSession

from database import db_session
from models import EmailAccount, OfferEmail
from services.mailing_deliverability import inbox_account_gap_sec, inbox_stagger_ms
from services.mailing_send import send_mailing_one_parallel
from services.sender import normalize_send_error
from services.smtp_proxy_send import pick_sticky_proxy_for_fast_mailing

logger = logging.getLogger(__name__)

BURST_SMTP_RETRIES = max(1, min(4, int(os.getenv("BURST_SMTP_RETRIES", "2"))))
BURST_RETRY_PAUSE_SEC = max(
    0.0, min(1.0, float(os.getenv("BURST_RETRY_PAUSE_SEC", "0.08")))
)
BURST_PER_LETTER_TIMEOUT_SEC = max(
    20, min(90, int(os.getenv("BURST_PER_LETTER_TIMEOUT_SEC", "45")))
)


def shuffle_accounts(accounts: Sequence[EmailAccount]) -> List[EmailAccount]:
    out = list(accounts)
    random.shuffle(out)
    return out


def bucket_targets_by_account(
    targets: Sequence[OfferEmail],
    accounts: Sequence[EmailAccount],
) -> dict[int, List[OfferEmail]]:
    buckets: dict[int, List[OfferEmail]] = defaultdict(list)
    if not accounts:
        return buckets
    acc_list = list(accounts)
    for i, tgt in enumerate(targets):
        acc = acc_list[i % len(acc_list)]
        buckets[int(acc.id)].append(tgt)
    return buckets


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


async def _drain_account_bucket(
    *,
    db_user_id: int,
    account: EmailAccount,
    targets: Sequence[OfferEmail],
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

    sent = failed = 0
    gap = inbox_account_gap_sec()
    for idx, tgt in enumerate(targets):
        if idx > 0 and gap > 0:
            await asyncio.sleep(gap + random.uniform(0, 0.4))
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
            sent += 1
            await on_success(tgt, subject, (account.email or "").strip())
        else:
            failed += 1
            await on_failure(tgt, err, account)
    return sent, failed


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
    Параллельно по ящикам + inbox stagger (не одновременный залп).
    """
    if not targets or not accounts:
        return 0, 0, None, 0.0

    async with db_session() as session:
        sticky_px = await pick_sticky_proxy_for_fast_mailing(session, int(db_user_id))
    if not sticky_px:
        raise RuntimeError("NO_ROTATING_PROXY")

    sticky_proxy_id = int(sticky_px.id)
    shuffled = shuffle_accounts(accounts)
    buckets = bucket_targets_by_account(targets, shuffled)
    stagger_s = inbox_stagger_ms() / 1000.0

    active = [acc for acc in shuffled if buckets.get(int(acc.id))]
    t0 = time.perf_counter()
    results = await asyncio.gather(
        *[
            _drain_account_bucket(
                db_user_id=db_user_id,
                account=acc,
                targets=buckets.get(int(acc.id), []),
                sticky_proxy_id=sticky_proxy_id,
                sender_name=sender_name,
                build_message=build_message,
                on_success=on_success,
                on_failure=on_failure,
                start_delay_sec=(stagger_s * i) + random.uniform(0, stagger_s * 0.35),
            )
            for i, acc in enumerate(active)
        ]
    )
    elapsed = time.perf_counter() - t0
    sent = sum(r[0] for r in results)
    failed = sum(r[1] for r in results)
    logger.info(
        "[gag burst inbox] tg=%s sent=%s failed=%s targets=%s accounts=%s "
        "proxy=%s stagger_ms=%s elapsed=%.2fs",
        tg_user_id,
        sent,
        failed,
        len(targets),
        len(active),
        sticky_proxy_id,
        inbox_stagger_ms(),
        elapsed,
    )
    return sent, failed, sticky_proxy_id, elapsed
