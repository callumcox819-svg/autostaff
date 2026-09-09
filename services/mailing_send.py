"""Рассылка /send: SMTP+NOOP как в обычном софте; IMAP Sent — только по флагу."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional, Tuple

from sqlalchemy.ext.asyncio import AsyncSession

from models import EmailAccount
from services.sender import normalize_send_error, should_retry_send_with_other_proxy
from services.smtp_delivery_verify import verify_message_in_sent
from services.smtp_proxy_send import (
    MAIL_SMTP_MAX_PROXIES,
    MAIL_SMTP_TIMEOUT_SEC,
    send_email_via_account_with_proxy,
    send_email_via_account_with_proxy_isolated,
)

logger = logging.getLogger(__name__)

# Как в типичном софте: успех = SMTP 250 + NOOP (в sender.py). IMAP — опционально.
MAIL_VERIFY_SENT = os.getenv("MAIL_VERIFY_SENT", "0").strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)
MAIL_VERIFY_SENT_DELAY_SEC = max(2, min(8, int(os.getenv("MAIL_VERIFY_SENT_DELAY_SEC", "3"))))
MAIL_SEND_RETRIES = max(1, min(3, int(os.getenv("MAIL_SEND_RETRIES", "2"))))
# Reconnect sticky делается внутри smtp_proxy_send (3×); снаружи не размножаем.
MAIL_FAST_SEND_RETRIES = max(
    1, min(3, int(os.getenv("MAIL_FAST_SEND_RETRIES", "1")))
)
# 0 = все активные ящики за одну волну (параллельно)
MAIL_FAST_PARALLEL_ACCOUNTS = max(
    0, min(50, int(os.getenv("MAIL_FAST_PARALLEL_ACCOUNTS", "0")))
)
MAIL_SEND_RETRY_PAUSE_SEC = max(
    1.0, min(8.0, float(os.getenv("MAIL_SEND_RETRY_PAUSE_SEC", "2")))
)
MAIL_FAST_SEND_RETRY_PAUSE_SEC = max(
    0.0, min(2.0, float(os.getenv("MAIL_FAST_SEND_RETRY_PAUSE_SEC", "0.25")))
)


def mailing_send_overall_timeout_sec(*, fast_mailing: bool = False) -> int:
    """Лимит на одно письмо: прокси × таймаут × попытки (без 10-минутных зависаний)."""
    if fast_mailing:
        from services.smtp_proxy_send import MAIL_FAST_SMTP_TIMEOUT_SEC

        retries = MAIL_FAST_SEND_RETRIES
        proxy_tries = 1
        per = proxy_tries * MAIL_FAST_SMTP_TIMEOUT_SEC + 15
        raw = per * retries + retries * MAIL_FAST_SEND_RETRY_PAUSE_SEC + 10
        fast_override = (os.getenv("SEND_ONE_TIMEOUT_FAST") or "").strip()
        if fast_override.isdigit():
            return max(45, min(240, int(fast_override)))
        return max(60, min(240, int(raw)))

    retries = MAIL_SEND_RETRIES
    proxy_tries = MAIL_SMTP_MAX_PROXIES
    per = proxy_tries * MAIL_SMTP_TIMEOUT_SEC + 30
    raw = per * retries + retries * MAIL_SEND_RETRY_PAUSE_SEC + 15
    return max(60, min(240, int(os.getenv("SEND_ONE_TIMEOUT", str(int(raw))))))


def _retry_after_failure(err: str | None) -> bool:
    return should_retry_send_with_other_proxy(err)


async def send_mailing_one(
    session: AsyncSession,
    user_id: int,
    account: EmailAccount,
    to_email: str,
    subject: str,
    body: str,
    sender_name: Optional[str] = None,
    *,
    fast_mailing: bool = False,
) -> Tuple[bool, Optional[str], Optional[str]]:
    last_err: Optional[str] = None
    last_msgid: Optional[str] = None
    max_retries = MAIL_FAST_SEND_RETRIES if fast_mailing else MAIL_SEND_RETRIES
    retry_pause = (
        MAIL_FAST_SEND_RETRY_PAUSE_SEC if fast_mailing else MAIL_SEND_RETRY_PAUSE_SEC
    )

    for attempt in range(1, max_retries + 1):
        ok, err, msgid = await send_email_via_account_with_proxy(
            session,
            int(user_id),
            account,
            to_email,
            subject,
            body,
            sender_name=sender_name,
            fast=False,
            mailing_fast=fast_mailing,
        )
        err = normalize_send_error(err)
        last_err = err
        last_msgid = msgid

        if not ok:
            if _retry_after_failure(err) and attempt < max_retries:
                if retry_pause > 0:
                    await asyncio.sleep(retry_pause)
                continue
            return False, err, msgid

        if MAIL_VERIFY_SENT:
            await asyncio.sleep(MAIL_VERIFY_SENT_DELAY_SEC)
            try:
                verified, verify_msg = await verify_message_in_sent(
                    account.email,
                    account.password or "",
                    subject=subject,
                    to_email=to_email,
                    message_id=msgid,
                )
            except Exception as e:
                verified, verify_msg = False, str(e)
            if not verified:
                last_err = normalize_send_error(
                    f"SMTP_ACCEPTED_NOT_IN_SENT|verify|{verify_msg or 'not in Sent'}"
                )
                if attempt < max_retries:
                    if retry_pause > 0:
                        await asyncio.sleep(retry_pause)
                    continue
                return False, last_err, msgid

        return True, None, msgid

    return False, last_err or "UNKNOWN", last_msgid


async def send_mailing_one_parallel(
    session: AsyncSession,
    user_id: int,
    account: EmailAccount,
    to_email: str,
    subject: str,
    body: str,
    sender_name: Optional[str] = None,
    *,
    sticky_proxy_id: int | None = None,
) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Фаст-волна: параллельный SMTP через один ротирующий SOCKS5 (новое соединение = новый IP).
    """
    last_err: Optional[str] = None
    last_msgid: Optional[str] = None

    for attempt in range(1, MAIL_FAST_SEND_RETRIES + 1):
        ok, err, msgid = await send_email_via_account_with_proxy_isolated(
            session,
            int(user_id),
            account,
            to_email,
            subject,
            body,
            sender_name=sender_name,
            mailing_fast=True,
            sticky_proxy_id=sticky_proxy_id,
        )
        err = normalize_send_error(err)
        last_err = err
        last_msgid = msgid
        if ok:
            return True, None, msgid
        if _retry_after_failure(err) and attempt < MAIL_FAST_SEND_RETRIES:
            if MAIL_FAST_SEND_RETRY_PAUSE_SEC > 0:
                await asyncio.sleep(MAIL_FAST_SEND_RETRY_PAUSE_SEC)
            continue
        return False, err, msgid

    return False, last_err or "UNKNOWN", last_msgid


# совместимость
send_mailing_one_verified = send_mailing_one
