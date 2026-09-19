"""Контроль SMTP-блокировок: ящик остаётся для IMAP, рассылка с него снимается."""

from __future__ import annotations

import asyncio
import logging
import os
import random
from datetime import datetime, timedelta

import html

from aiogram import Bot
from sqlalchemy import or_, select as sa_select
from sqlalchemy.ext.asyncio import AsyncSession

from models import EmailAccount, User
from services.sender import normalize_send_error
from services.country_scope import get_scoped_setting
from utils.ui_emoji import html_emoji

logger = logging.getLogger(__name__)

_COOLDOWN_TASK: asyncio.Task | None = None


def _truthy(v: str | None) -> bool:
    return str(v or "").strip().lower() in {"1", "true", "yes", "on", "y"}


def smtp_block_cooldown_hours_range() -> tuple[float, float]:
    """Глобальная пауза перед автовозвратом в рассылку (часы)."""
    try:
        lo = float(os.getenv("SMTP_BLOCK_COOLDOWN_MIN_HOURS", "5") or "5")
    except ValueError:
        lo = 5.0
    try:
        hi = float(os.getenv("SMTP_BLOCK_COOLDOWN_MAX_HOURS", "6") or "6")
    except ValueError:
        hi = 6.0
    lo = max(0.25, lo)
    hi = max(lo, hi)
    return lo, hi


def new_smtp_blocked_until(*, now: datetime | None = None) -> datetime:
    """Случайный дедлайн в диапазоне 5–6 ч (или из env)."""
    lo, hi = smtp_block_cooldown_hours_range()
    hours = random.uniform(lo, hi)
    return (now or datetime.utcnow()) + timedelta(hours=hours)


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
    """
    SMTP-check не снимает smtp_blocked (логин ≠ лимит).
    Автовозврат делает restore_due_smtp_blocked_accounts после паузы.
    """
    return is_smtp_blocked_status(getattr(account, "status", None))


def apply_smtp_blocked_fields(account: EmailAccount, err: str | None = None) -> bool:
    """
    Выставить smtp_blocked + дедлайн паузы.
    Если уже blocked — таймер не сбрасываем.
    Возвращает True, если статус только что стал smtp_blocked.
    """
    was_blocked = is_smtp_blocked_status(getattr(account, "status", None))
    account.status = "smtp_blocked"
    if err is not None:
        account.last_error = (err or "")[:1000]
    if not was_blocked or getattr(account, "smtp_blocked_until", None) is None:
        account.smtp_blocked_until = new_smtp_blocked_until()
    return not was_blocked


def clear_smtp_blocked_fields(account: EmailAccount) -> None:
    """Вернуть ящик в рассылку."""
    account.status = "active"
    account.last_error = None
    account.smtp_blocked_until = None


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
    lo, hi = smtp_block_cooldown_hours_range()
    pause = f"{lo:g}–{hi:g} ч" if abs(hi - lo) > 0.05 else f"{lo:g} ч"
    return (
        f"{lead}{html_emoji('yellow')} {html_emoji('stop')} "
        f"<b>Почта удалена с рассылки</b>, {html_emoji('email')} "
        f"<b>оставлена для получения писем</b> (IMAP). "
        f"Автовозврат в SMTP через ~{pause}."
    )


async def block_control_enabled(session: AsyncSession, db_user_id: int) -> bool:
    user = (
        await session.execute(sa_select(User).where(User.id == int(db_user_id)).limit(1))
    ).scalars().first()
    if not user:
        return False
    return _truthy(await get_scoped_setting(session, user, "block_control"))


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

    newly = apply_smtp_blocked_fields(account, err)
    try:
        await session.commit()
    except Exception:
        await session.rollback()
        raise

    if not newly:
        return True

    notify = force or await block_control_enabled(session, db_user_id)
    if bot and chat_id and notify:
        em = html.escape((account.email or "").strip())
        if force:
            # IMAP Message blocked: одна короткая строка, без карточки письма.
            try:
                await bot.send_message(
                    int(chat_id),
                    f"{html_emoji('yellow')} <code>{em}</code> — SMTP off "
                    f"(Message blocked). IMAP ok · авто ~"
                    f"{smtp_block_cooldown_hours_range()[0]:g}–"
                    f"{smtp_block_cooldown_hours_range()[1]:g} ч.",
                    parse_mode="HTML",
                )
            except Exception:
                pass
        else:
            await notify_smtp_stream_stopped_for_imap(
                bot,
                int(chat_id),
                account.email or "",
                reason=err,
            )
            await bot.send_message(
                int(chat_id),
                smtp_removed_from_mailing_notice_html(lead="")
                + f"\n<code>{em}</code>",
                parse_mode="HTML",
            )
    return True


async def restore_due_smtp_blocked_accounts(session: AsyncSession) -> int:
    """Вернуть в рассылку ящики, у которых истекла пауза smtp_blocked. Глобально."""
    now = datetime.utcnow()
    lo, _hi = smtp_block_cooldown_hours_range()
    legacy_cutoff = now - timedelta(hours=lo)
    rows = (
        await session.execute(
            sa_select(EmailAccount).where(
                EmailAccount.status == "smtp_blocked",
                or_(
                    EmailAccount.smtp_blocked_until <= now,
                    EmailAccount.smtp_blocked_until.is_(None),
                ),
            )
        )
    ).scalars().all()

    restored = 0
    changed = False
    for acc in rows:
        until = getattr(acc, "smtp_blocked_until", None)
        if until is not None and until > now:
            continue
        if until is None:
            updated = getattr(acc, "updated_at", None)
            if updated is not None and updated > legacy_cutoff:
                # Ещё рано: проставим дедлайн от updated_at.
                acc.smtp_blocked_until = updated + timedelta(hours=lo)
                changed = True
                continue
        clear_smtp_blocked_fields(acc)
        restored += 1
        changed = True

    if changed:
        try:
            await session.commit()
        except Exception:
            await session.rollback()
            raise
    return restored


async def _smtp_block_cooldown_loop() -> None:
    try:
        interval = int(os.getenv("SMTP_BLOCK_COOLDOWN_POLL_SEC", "300") or "300")
    except ValueError:
        interval = 300
    interval = max(60, interval)
    lo, hi = smtp_block_cooldown_hours_range()
    logger.info(
        "SMTP block cooldown worker: poll=%ss, pause=%.2f–%.2fh",
        interval,
        lo,
        hi,
    )
    while True:
        try:
            from database import Session

            async with Session() as session:
                n = await restore_due_smtp_blocked_accounts(session)
            if n:
                logger.info("SMTP cooldown: restored %s account(s) to mailing", n)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("SMTP cooldown restore failed")
        await asyncio.sleep(interval)


def start_smtp_block_cooldown_worker() -> None:
    """Фон: раз в N минут возвращает smtp_blocked → active после паузы 5–6 ч."""
    global _COOLDOWN_TASK
    if os.getenv("SMTP_BLOCK_AUTO_RESTORE", "1").strip().lower() in {
        "0",
        "false",
        "no",
        "off",
    }:
        logger.info("SMTP block auto-restore disabled (SMTP_BLOCK_AUTO_RESTORE=0)")
        return
    if _COOLDOWN_TASK and not _COOLDOWN_TASK.done():
        return
    _COOLDOWN_TASK = asyncio.create_task(
        _smtp_block_cooldown_loop(), name="smtp-block-cooldown"
    )
