"""GAG /send — только burst-рассылка (2–5 с), ротация ящиков и текстов."""

from __future__ import annotations

import asyncio
import logging
from typing import List, Optional, Tuple

from aiogram import Bot, Router, F
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.exceptions import TelegramNetworkError

from sqlalchemy import select, func, delete
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from database import db_session
from models import EmailAccount, OfferEmail, Offer, User, Proxy

from services.burst_mailer import run_burst_mailing
from services.mailing_send import MAIL_VERIFY_SENT
from services.users import get_or_create_user
from services.user_settings import get_user_setting
from services.placeholders import apply_placeholders

from handlers.status import tg_answer_safe
from services.sender import normalize_send_error
from services.smtp_block_control import mark_account_smtp_blocked
from services.smtp_account_check import is_account_no_access_error
from keyboards.main_menu import is_send_trigger, main_menu_kb

from services.sending_state import SendingState
from services.sending_state import get_state as _get_sending_state
from services.sending_state import set_state as _set_sending_state

router = Router(name="send")
logger = logging.getLogger(__name__)

from services.aqua_keys import AQUA_PROFILE_ADDRESS_KEY, AQUA_PROFILE_NAME_KEY


async def _edit_status_text(status_msg: Message, text: str, **kwargs) -> None:
    kwargs.pop("reply_markup", None)
    await status_msg.edit_text(text, **kwargs)


def get_sending_state(user_id: int) -> Optional[SendingState]:
    return _get_sending_state(user_id)


def set_sending_state(user_id: int, state: Optional[SendingState] = None, **kwargs) -> SendingState:
    if state is not None:
        return _set_sending_state(user_id, **getattr(state, "__dict__", {}))
    return _set_sending_state(user_id, **kwargs)


async def _safe_commit(session: AsyncSession):
    try:
        await session.commit()
    except OperationalError:
        await session.rollback()
        raise


async def _safe_rollback(session: AsyncSession):
    try:
        await session.rollback()
    except Exception:
        pass


async def _get_active_accounts(session: AsyncSession, user_id: int) -> List[EmailAccount]:
    rows = (
        await session.execute(
            select(EmailAccount).where(
                EmailAccount.user_id == user_id,
                EmailAccount.status.in_(("active", "enabled")),
            )
        )
    ).scalars().all()
    return list(rows)


async def _mailing_reset_since_dt(session: AsyncSession, user_id: int):
    from services.mailing_reset import get_mailing_reset_since, parse_mailing_reset_since

    raw = await get_mailing_reset_since(session, user_id)
    return parse_mailing_reset_since(raw)


async def _get_targets(session: AsyncSession, user_id: int) -> List[OfferEmail]:
    reset_dt = await _mailing_reset_since_dt(session, user_id)
    stmt = (
        select(OfferEmail)
        .join(Offer, Offer.id == OfferEmail.offer_id)
        .where(Offer.user_id == user_id)
        .options(selectinload(OfferEmail.offer))
        .order_by(OfferEmail.id.asc())
    )
    if reset_dt is not None:
        stmt = stmt.where(Offer.created_at >= reset_dt)
    return list((await session.execute(stmt)).scalars().all())


async def _get_targets_count(session: AsyncSession, user_id: int) -> int:
    reset_dt = await _mailing_reset_since_dt(session, user_id)
    stmt = (
        select(func.count(OfferEmail.id))
        .select_from(OfferEmail)
        .join(Offer, Offer.id == OfferEmail.offer_id)
        .where(Offer.user_id == user_id)
    )
    if reset_dt is not None:
        stmt = stmt.where(Offer.created_at >= reset_dt)
    return (await session.execute(stmt)).scalar() or 0


async def _purge_target(session: AsyncSession, user_id: int, offer_email_id: int):
    try:
        await session.execute(
            delete(OfferEmail)
            .where(OfferEmail.id == offer_email_id)
            .where(OfferEmail.offer_id.in_(select(Offer.id).where(Offer.user_id == user_id)))
        )
        await _safe_commit(session)
    except Exception:
        await _safe_rollback(session)


async def _record_successful_send(
    session: AsyncSession,
    *,
    user_id: int,
    tgt: OfferEmail,
    subject: str,
    from_account_email: str,
) -> None:
    from services.mailing_send_log import record_mailing_send

    try:
        await record_mailing_send(
            session,
            user_id=int(user_id),
            offer_id=int(tgt.offer_id),
            recipient_email=(tgt.email or "").strip(),
            mail_subject=subject,
            from_account_email=from_account_email,
            offer_email_id=int(tgt.id),
        )
        await _safe_commit(session)
    except Exception:
        await _safe_rollback(session)
        logger.exception("record_mailing_send failed offer_id=%s", getattr(tgt, "offer_id", None))


async def _build_message_for_target(
    session: AsyncSession, tg_user_id: int, tgt: OfferEmail
) -> Tuple[str, str]:
    """Случайный умный пресет / первое смс на каждый адрес (ротация текстов)."""
    offer: Offer | None = getattr(tgt, "offer", None)

    from services.offer_storage import offer_effective_title

    item_title = offer_effective_title(offer)
    price = (getattr(offer, "price", "") or "").strip()
    link = (getattr(offer, "link", "") or "").strip()
    image_url = (getattr(offer, "photo", "") or "").strip()

    user = await get_or_create_user(session, tg_user_id)
    buyer_name = ((await get_user_setting(session, user, AQUA_PROFILE_NAME_KEY)) or "").strip()
    address = ((await get_user_setting(session, user, AQUA_PROFILE_ADDRESS_KEY)) or "").strip()

    ctx = {
        "ITEM_TITLE": item_title,
        "PRICE": price,
        "BUYER_NAME": buyer_name,
        "ADDRESS": address,
        "IMAGE_URL": image_url,
    }

    base_text = ""
    try:
        from handlers.templates import pick_random_smart_preset

        base_text = await pick_random_smart_preset(tg_user_id, item_title)
    except Exception:
        base_text = ""
    if not (base_text or "").strip():
        base_text = (
            "Grüezi! Ist der Artikel noch verfügbar? " + (item_title or "OFFER")
        ).strip()

    body = apply_placeholders(base_text, link=link, ctx=ctx)
    from services.offer_text import finalize_mailing_body

    body = finalize_mailing_body(body, item_title)

    from services.subject_offer import SUBJECT_TEMPLATE_SETTING
    from services.mailing_deliverability import finalize_inbox_mail, pick_rotating_subject

    user_tpl = (await get_user_setting(session, user, SUBJECT_TEMPLATE_SETTING) or "").strip()
    subject = pick_rotating_subject(item_title or "", user_template=user_tpl or None)
    subject, body = finalize_inbox_mail(subject, body)
    return subject, body


@router.message(Command("send"))
@router.message(F.text.func(lambda m: is_send_trigger(getattr(m, "text", None))))
async def send_cmd(message: Message):
    await start_sending(message)


async def start_sending(message: Message):
    tg_user_id = message.from_user.id
    chat_id = message.chat.id
    bot = message.bot

    status_msg = await message.answer("⏳ Проверяю очередь и аккаунты…", parse_mode="HTML")

    try:
        await _start_sending_inner(
            message=message,
            status_msg=status_msg,
            tg_user_id=tg_user_id,
            chat_id=chat_id,
            bot=bot,
        )
    except Exception:
        logger.exception("start_sending failed tg=%s", tg_user_id)
        try:
            await _edit_status_text(
                status_msg,
                "❌ Ошибка запуска рассылки. Попробуйте /send снова.",
            )
        except Exception:
            await tg_answer_safe(
                message,
                "❌ Ошибка запуска рассылки. Попробуйте /send снова.",
                reply_markup=main_menu_kb(tg_user_id),
            )


async def _start_sending_inner(
    *,
    message: Message,
    status_msg: Message,
    tg_user_id: int,
    chat_id: int,
    bot: Bot,
) -> None:
    async with db_session() as session:
        db_user = await get_or_create_user(session, int(tg_user_id))
        db_user_id = db_user.id
        accounts = await _get_active_accounts(session, db_user_id)
        total_targets = await _get_targets_count(session, db_user_id)

        if not accounts:
            await _edit_status_text(
                status_msg,
                "❌ Нет активных аккаунтов.\nДобавьте почту в «Настройки → E-mail».",
            )
            return

        if total_targets <= 0:
            await _edit_status_text(
                status_msg,
                "❌ Очередь пуста — нет email после валидации.",
            )
            return

        state = get_sending_state(tg_user_id)
        if state and getattr(state, "is_running", False):
            await _edit_status_text(status_msg, "⚠️ Рассылка уже запущена.")
            return

        from proxy_manager import is_socks5_proxy

        all_px = (
            await session.execute(select(Proxy).where(Proxy.user_id == db_user_id))
        ).scalars().all()
        if not any(is_socks5_proxy(p) for p in all_px):
            await _edit_status_text(
                status_msg,
                "❌ Нет SOCKS5. Добавьте ротирующий gateway в «Прокси».",
            )
            return

    try:
        await _edit_status_text(
            status_msg,
            "⏳ Проверяю ротирующий SOCKS5…\n<i>~10 сек.</i>",
            parse_mode="HTML",
        )
    except Exception:
        pass

    from services.mailing_proxy_health import preflight_proxies_for_mailing
    from services.smtp_proxy_send import pick_sticky_proxy_for_fast_mailing

    sticky_proxy_id: int | None = None
    async with db_session() as session:
        sticky_px = await pick_sticky_proxy_for_fast_mailing(session, int(db_user_id))
        if sticky_px:
            sticky_proxy_id = int(sticky_px.id)

    px_ok, px_summary, px_detail = await preflight_proxies_for_mailing(
        int(db_user_id),
        fast=True,
        sticky_proxy_id=sticky_proxy_id,
    )
    if not px_ok:
        try:
            await _edit_status_text(
                status_msg,
                "❌ <b>Рассылка не запущена</b>\n\n" + px_detail,
                parse_mode="HTML",
            )
        except Exception:
            await tg_answer_safe(
                message,
                "❌ Рассылка не запущена.\n\n" + px_detail,
                reply_markup=main_menu_kb(tg_user_id),
                parse_mode="HTML",
            )
        return

    if not sticky_proxy_id:
        await _edit_status_text(
            status_msg,
            "❌ Нет 🟢 ротирующего SOCKS5. Проверьте «Прокси».",
            parse_mode="HTML",
        )
        return

    state = SendingState(
        user_id=tg_user_id,
        is_running=True,
        is_stopping=False,
        total_targets=total_targets,
        sent_count=0,
        failed_count=0,
        accounts_total=len(accounts),
        accounts_active=len(accounts),
        last_error="",
        last_status="BURST",
        fast_mailing=True,
        sticky_proxy_id=sticky_proxy_id,
    )
    set_sending_state(tg_user_id, state=state)

    from services.mailing_active_db import set_mailing_active

    await set_mailing_active(tg_user_id, active=True)

    try:
        await _edit_status_text(
            status_msg,
            "⚡ <b>Burst-рассылка GAG</b> (inbox-safe)\n"
            f"В очереди: <b>{total_targets}</b> · ящиков: <b>{len(accounts)}</b>\n"
            f"{px_detail}\n"
            f"SOCKS5 id=<b>{sticky_proxy_id}</b> (ротация IP)\n"
            "Inbox: plain · без ссылок · уник. тема/текст · stagger ящиков\n"
            f"Успех: <b>{'IMAP Sent' if MAIL_VERIFY_SENT else 'SMTP 250+NOOP'}</b>",
            parse_mode="HTML",
        )
    except Exception:
        pass

    asyncio.create_task(
        _burst_sending_loop(bot=bot, chat_id=chat_id, tg_user_id=tg_user_id)
    )


async def _handle_send_failure(
    *,
    session: AsyncSession,
    db_user_id: int,
    state: SendingState,
    tgt: OfferEmail,
    err: str,
    acc: EmailAccount,
    bot: Bot | None = None,
    chat_id: int | None = None,
) -> bool:
    err = normalize_send_error(err)
    state.failed_count += 1
    state.last_error = err or "UNKNOWN"
    state.last_failed_to = (tgt.email or "").strip()

    if await mark_account_smtp_blocked(
        session,
        acc,
        err,
        db_user_id=db_user_id,
        bot=bot,
        chat_id=chat_id,
    ):
        return True

    if is_account_no_access_error(err):
        try:
            await session.delete(acc)
            await session.commit()
            logger.warning("Deleted account (no access): %s", acc.email)
        except Exception:
            await session.rollback()
        return True

    err_u = (err or "").upper()
    if (
        "RECIPIENT_DEAD" in err_u
        or "5.1.1" in err_u
        or "5.5.0" in err_u
        or "MAILBOX UNAVAILABLE" in err_u
        or "ADDRESS NOT FOUND" in err_u
    ):
        await _purge_target(session, db_user_id, int(tgt.id))
    return False


async def _notify_sending_finished(*, bot: Bot, chat_id: int, tg_user_id: int) -> None:
    state = get_sending_state(tg_user_id)
    if not state:
        return

    pending = 0
    try:
        async with db_session() as session:
            user = await get_or_create_user(session, tg_user_id)
            pending = int(await _get_targets_count(session, int(user.id)))
    except Exception:
        pass

    sent = int(state.sent_count)
    failed = int(state.failed_count)
    status = (state.last_status or "").upper()
    elapsed = getattr(state, "burst_elapsed_sec", None)

    if state.is_stopping:
        title = "⏹ <b>Рассылка остановлена</b>"
    elif status in ("DONE", "BURST"):
        title = "✅ <b>Burst-рассылка завершена</b>"
    else:
        title = "⚠️ <b>Рассылка прервана</b>"

    time_line = ""
    if elapsed is not None:
        time_line = f"\nВремя: <b>{elapsed:.1f} с</b>"

    text = (
        f"{title}\n\n"
        f"Отправлено: <b>{sent}</b>\n"
        f"Ошибок: <b>{failed}</b>\n"
        f"В очереди: <b>{pending}</b>{time_line}\n\n"
        "<i>Inbox получателя: проверьте не только Spam. "
        "Сначала «Тест маил» на свой ящик.</i>"
    )
    if failed > 0 and (state.last_error or "").strip() not in ("", "-"):
        from handlers.status import _humanize_send_error

        who = f"\nПоследний: <code>{state.last_failed_to}</code>" if state.last_failed_to else ""
        text += f"\n\n{_humanize_send_error(normalize_send_error(state.last_error))}{who}"

    try:
        await bot.send_message(
            chat_id,
            text,
            parse_mode="HTML",
            reply_markup=main_menu_kb(tg_user_id),
        )
    except Exception:
        logger.exception("failed to send mailing finished notification user=%s", tg_user_id)


async def _burst_sending_loop(*, bot: Bot, chat_id: int, tg_user_id: int) -> None:
    state = get_sending_state(tg_user_id) or SendingState(user_id=tg_user_id)
    blocked_account_ids: set[int] = set()

    try:
        async with db_session() as session:
            user = await get_or_create_user(session, tg_user_id)
            db_user_id = int(user.id)
            sender_name = getattr(user, "sender_name", None)

            accounts = await _get_active_accounts(session, db_user_id)
            targets = await _get_targets(session, db_user_id)

            if not accounts or not targets:
                state.is_running = False
                state.last_status = "DONE"
                set_sending_state(tg_user_id, state=state)
                return

            state.last_status = "BURST"
            state.current_to = f"⚡ burst × {len(targets)}"
            set_sending_state(tg_user_id, state=state)

            async def build_message(session: AsyncSession, tgt: OfferEmail) -> Tuple[str, str]:
                return await _build_message_for_target(session, tg_user_id, tgt)

            async def on_success(tgt: OfferEmail, subject: str, from_email: str) -> None:
                state.sent_count += 1
                set_sending_state(tg_user_id, state=state)
                async with db_session() as ws:
                    await _record_successful_send(
                        ws,
                        user_id=db_user_id,
                        tgt=tgt,
                        subject=subject,
                        from_account_email=from_email,
                    )
                    await _purge_target(ws, db_user_id, int(tgt.id))

            async def on_failure(tgt: OfferEmail, err: str, acc: EmailAccount) -> bool:
                async with db_session() as ws:
                    blocked = await _handle_send_failure(
                        session=ws,
                        db_user_id=db_user_id,
                        state=state,
                        tgt=tgt,
                        err=err,
                        acc=acc,
                        bot=bot,
                        chat_id=chat_id,
                    )
                if blocked:
                    blocked_account_ids.add(int(acc.id))
                set_sending_state(tg_user_id, state=state)
                return blocked

            sent, failed, proxy_id, elapsed = await run_burst_mailing(
                db_user_id=db_user_id,
                tg_user_id=tg_user_id,
                accounts=[a for a in accounts if int(a.id) not in blocked_account_ids],
                targets=targets,
                sender_name=None,
                build_message=build_message,
                on_success=on_success,
                on_failure=on_failure,
            )

            state.sent_count = sent
            state.failed_count = failed
            state.burst_elapsed_sec = elapsed
            if proxy_id:
                state.sticky_proxy_id = proxy_id
            state.current_to = ""
            state.is_running = False
            state.last_status = "DONE"
            set_sending_state(tg_user_id, state=state)

    except RuntimeError as e:
        if "NO_ROTATING_PROXY" in str(e):
            state.last_error = "PROXY_ERROR|no_rotating_proxy"
        else:
            state.last_error = normalize_send_error(str(e))
        state.is_running = False
        set_sending_state(tg_user_id, state=state)
    except TelegramNetworkError:
        state.is_running = False
        state.last_error = "TG_ERROR|network|Telegram network error"
        set_sending_state(tg_user_id, state=state)
    except Exception as e:
        state.is_running = False
        state.last_error = normalize_send_error(str(e))
        set_sending_state(tg_user_id, state=state)
        logger.exception("burst sending failed user=%s", tg_user_id)
    finally:
        state = get_sending_state(tg_user_id) or state
        if state.is_running:
            state.is_running = False
            set_sending_state(tg_user_id, state=state)
        try:
            from services.mailing_active_db import set_mailing_active

            await set_mailing_active(tg_user_id, active=False)
        except Exception:
            logger.exception("clear mailing_active flag tg=%s", tg_user_id)
        await _notify_sending_finished(bot=bot, chat_id=chat_id, tg_user_id=tg_user_id)
