"""Контроль SMTP-блокировок: ящик остаётся для IMAP, рассылка с него снимается."""

from __future__ import annotations
from utils.ui_emoji import html_emoji, menu_path, toast, msg_fail, msg_ok, msg_wait, msg_warn

import html

from aiogram import Bot
from sqlalchemy import select as sa_select
from sqlalchemy.ext.asyncio import AsyncSession

from models import EmailAccount, User
from services.sender import normalize_send_error
from services.user_settings import get_user_setting


def _truthy(v: str | None) -> bool:
    return str(v or "").strip().lower() in {"1", "true", "yes", "on", "y"}


def is_temporary_smtp_busy(err: str | None) -> bool:
    """421 / 4.4.5 Server busy — Gmail перегружен, не бан и не дневной лимит."""
    s = normalize_send_error(err or "").lower()
    hard_quota = (
        "daily user sending limit",
        "sending limit exceeded",
        "user sending limit",
        "5.4.5",
    )
    if any(p in s for p in hard_quota):
        return False
    if "4.4.5" in s or "server busy" in s or "try again later" in s:
        return True
    # ACCOUNT_RATE_LIMIT:421:... без daily/5.4.5
    if ":421:" in s or s.endswith(":421") or " 421 " in f" {s} ":
        return "limit" not in s or "try again" in s
    return False


def is_smtp_account_block_error(err: str | None) -> bool:
    """Ошибка уровня ящика (лимит Gmail, блок, неверный пароль) — не ошибка одного получателя."""
    s = normalize_send_error(err or "")
    kind = s.split("|", 1)[0].split(":", 1)[0].strip().upper()
    if kind in (
        "RECIPIENT_DEAD",
        "RECIPIENT_REFUSED",
        "PROXY_ERROR",
        "SMTP_TIMEOUT",
        "SMTP_ACCEPTED_NOT_IN_SENT",
    ):
        return False
    # 421 busy — только пауза, ящик с рассылки НЕ снимаем
    if is_temporary_smtp_busy(s):
        return False
    if kind in (
        "ACCOUNT_BLOCKED",
        "ACCOUNT_INVALID_CREDENTIALS",
        "ACCOUNT_WEB_LOGIN_REQUIRED",
    ):
        return True
    # ACCOUNT_RATE_LIMIT: снимаем только при жёсткой квоте (не Server busy)
    if kind == "ACCOUNT_RATE_LIMIT":
        t = s.lower()
        return any(
            p in t
            for p in (
                "daily user sending limit",
                "sending limit exceeded",
                "user sending limit",
                "5.4.5",
            )
        )
    t = s.lower()
    # Обычный DSN / отбой на адрес получателя — ящик отправителя не блокируем.
    recipient_only = (
        "could not be delivered to one or more recipients",
        "your email could not be delivered",
        "system-generated message to inform you",
        "details of the email and the error",
        "no such user",
        "user unknown",
        "mailbox unavailable",
        "recipient address rejected",
        "address rejected",
        "undeliverable address",
        "delivery status notification",
        "mail delivery subsystem",
        "5.1.1",
        "5.1.0",
        "5.2.1",
        "5.4.4",
        "host 127.0.0.1",
    )
    if any(p in t for p in recipient_only):
        return False
    phrases = (
        "daily user sending limit",
        "sending limit exceeded",
        "user sending limit",
        "too many messages",
        "mailbox full",
        "account has been disabled",
        "web login required",
        "username and password not accepted",
        "5.4.5",
        "5.7.1",
        "message blocked",
    )
    return any(p in t for p in phrases)


def is_smtp_blocked_status(status: str | None) -> bool:
    return (status or "").strip().lower() == "smtp_blocked"


def smtp_blocked_should_persist(account: EmailAccount) -> bool:
    """smtp_blocked не снимать автоматически (SMTP-check только логин, не лимит 5.4.5)."""
    return is_smtp_blocked_status(getattr(account, "status", None))


def short_block_reason(err: str | None) -> str:
    s = normalize_send_error(err or "")
    if "|" in s:
        parts = s.split("|")
        if len(parts) >= 3 and parts[2].strip():
            return parts[2].strip()[:220]
        if len(parts) >= 2 and parts[1].strip():
            return parts[1].strip()[:220]
    return s[:220]


def smtp_removed_from_mailing_notice_html(*, lead: str = "\n\n") -> str:
    """Текст на карточке отбоя / уведомление: с рассылки сняли, IMAP оставили."""
    return (
        f"{lead}{html_emoji('yellow')} {html_emoji('stop')} "
        f"<b>Почта удалена с рассылки</b>, {html_emoji('email')} "
        f"<b>оставлена для получения писем</b> (IMAP)."
    )


async def block_control_enabled(session: AsyncSession, db_user_id: int) -> bool:
    user = (
        await session.execute(sa_select(User).where(User.id == int(db_user_id)).limit(1))
    ).scalars().first()
    if not user:
        return False
    return _truthy(await get_user_setting(session, user, "block_control"))


async def notify_smtp_stream_stopped_for_imap(
    bot: Bot,
    chat_id: int,
    account_email: str,
    *,
    reason: str | None = None,
) -> None:
    em = html.escape((account_email or "").strip())
    text = (
        f"{html_emoji('burst')} Поток SMTP для <code>{em}</code> завершён.\n"
        f"Оставляем ящик для IMAP (входящие)."
    )
    r = (reason or "").strip()
    if r:
        text += f"\n\n<code>{html.escape(short_block_reason(r))}</code>"
    await bot.send_message(int(chat_id), text, parse_mode="HTML")


async def mark_account_smtp_blocked(
    session: AsyncSession,
    account: EmailAccount,
    err: str,
    *,
    db_user_id: int,
    bot: Bot | None = None,
    chat_id: int | None = None,
    force: bool = False,
) -> bool:
    """
    Пометить ящик smtp_blocked и (если включён контроль блокировок) уведомить в Telegram.
    force=True — IMAP bounce (Message blocked), без проверки фраз SMTP-ошибки отправки.
    Возвращает True, если ящик снят с SMTP.
    """
    if not force and not is_smtp_account_block_error(err):
        return False

    row = await session.get(EmailAccount, int(account.id))
    if not row:
        return False
    account = row

    was_blocked = is_smtp_blocked_status(account.status)
    account.status = "smtp_blocked"
    account.last_error = (err or "")[:1000]
    try:
        await session.commit()
    except Exception:
        await session.rollback()
        raise

    if was_blocked:
        return True

    notify = force or await block_control_enabled(session, db_user_id)
    if bot and chat_id and notify:
        if not force:
            await notify_smtp_stream_stopped_for_imap(
                bot,
                int(chat_id),
                account.email or "",
                reason=err,
            )
            em = html.escape((account.email or "").strip())
            await bot.send_message(
                int(chat_id),
                smtp_removed_from_mailing_notice_html(lead="")
                + f"\n<code>{em}</code>",
                parse_mode="HTML",
            )
        # force (IMAP Message blocked): текст на карточке письма — без второго сообщения
    return True
