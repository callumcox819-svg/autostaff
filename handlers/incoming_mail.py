# handlers/incoming_mail.py
from __future__ import annotations

import asyncio
import html
import logging
import os
import re
from dataclasses import dataclass, field

from aiogram import Router, F
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import BufferedInputFile

from sqlalchemy import select as sa_select, func, select, update as sa_update
from sqlalchemy.exc import IntegrityError

from database import Session
from models import (
    EmailAccount,
    ConversationLink,
    Offer,
    OfferEmail,
    IncomingMail,
    User,
    UserSetting,
    QuickTemplate,
)

from services.users import get_or_create_user
from services.user_settings import get_user_setting
from services.aqua_keys import (
    AQUA_SERVICE_KEY,
    aqua_service_for_api,
    aqua_service_for_html_dir,
    get_user_aqua_api_keys_async,
    get_user_aqua_profile_display,
    get_user_aqua_service,
    get_user_profile_address,
    get_user_profile_buyer_name,
    is_valid_aqua_service,
)
from services.aqua_link import aqua_generate_for_offer
from services.aqua_network import generate_aqua_link, AquaError
from services.aqua_link import resolve_aqua_image_url
from services.incoming_mail_worker import (
    FULL_META,
    full_body_get,
    full_meta_get,
    _try_pin,
    build_mail_card_from_mail,
    resolve_offer_for_mail_card,
)
from services.offer_matching import (
    finalize_aqua_listing_context,
    product_title_from_subject,
    resolve_offer_for_aqua_link,
    subject_is_informative,
)
from services.offer_storage import offer_effective_photo, offer_effective_price, offer_effective_title
from services.smtp_proxy_send import send_email_via_account_with_proxy, user_has_active_mailing_proxy
from services.translate import translate_to_ru, _strip_html

# Email reply "presets" must use the same storage/UI as ⚡ Шаблоны (handlers/templates.py)
from handlers.templates import load_templates, TemplateItem
from utils.bg_jobs import is_running as bg_is_running, start as bg_start
from utils.callback_safe import callback_answer_safe, is_expired_callback_error
from utils.tg_flood import tg_call
from utils.ui_emoji import (
    html_emoji,
    inline_button,
    back_inline,
    menu_path,
    msg_fail,
    msg_ok,
    msg_wait,
    msg_warn,
    toast,
)

router = Router()

logger = logging.getLogger(__name__)


def _aqua_link_user_error(e: Exception) -> str:
    raw = str(e) or type(e).__name__
    blob = f"{type(e).__name__} {raw}".lower()
    if (
        "foreignkey" in blob
        or "integrityerror" in blob
        or "resolved_offer_id" in blob
    ):
        return (
            "Лот с карточки уже удалён из базы. "
            "Загрузите JSON, провалидируйте email и снова нажмите «Создать ссылку»."
        )
    if "timeouterror" in blob or "таймаут" in blob:
        return (
            "INC-CORE не ответил вовремя. "
            "Подождите 20–30 сек и нажмите «Создать ссылку» ещё раз."
        )
    return raw[:350]


async def _run_aqua_link_bg(callback: CallbackQuery, work) -> None:
    """Фоновая AQUA-ссылка: при падении — сообщение в чат (не молчим)."""
    try:
        await work()
    except Exception as e:
        if is_expired_callback_error(e):
            logger.warning(
                "aqua_link: stale Telegram callback (link work may have finished) tg=%s",
                callback.from_user.id,
            )
            return
        logger.exception("aqua_link background failed tg=%s", callback.from_user.id)
        try:
            await callback.message.answer(
                f"{html_emoji('fail')} <b>Ошибка создания ссылки</b>\n<code>{_e(_aqua_link_user_error(e))}</code>",
                parse_mode="HTML",
            )
        except Exception:
            pass


def _incoming_smtp_wait_sec() -> int:
    from services.smtp_proxy_send import (
        REPLY_SMTP_MAX_PROXIES,
        REPLY_SMTP_PROXY_RETRIES,
        REPLY_SMTP_TIMEOUT_SEC,
    )

    default = REPLY_SMTP_MAX_PROXIES * REPLY_SMTP_TIMEOUT_SEC * REPLY_SMTP_PROXY_RETRIES + 30
    return max(90, min(240, int(os.getenv("INCOMING_SMTP_TIMEOUT_SEC", str(int(default))))))
REPLY_CHOICE_TEXT = "Выберите вариант"

COUNTRY_KEY = "country"
HTML_NICK_KEY = "html_nick"
HTML_SIGNATURE_KEY = "html_signature"
HTML_SUBJECT_KEY = "html_subject_theme"


async def _aqua_generate_link(
    session,
    user: User,
    *,
    title: str,
    price: str,
    listing_url: str | None,
    image: str | None = None,
) -> str:
    from services.aqua_link import aqua_generate_for_offer
    from services.offer_storage import find_offer_by_link
    from types import SimpleNamespace

    listing = (listing_url or "").strip()
    offer = None
    if listing:
        offer = await find_offer_by_link(session, user_id=int(user.id), ad_url=listing)
    if offer is None:
        offer = SimpleNamespace(
            title=(title or "").strip() or "Item",
            price=(price or "").strip() or None,
            photo=(image or "").strip() or None,
            link=listing or None,
            item_link=listing or None,
            raw_json=None,
        )
    return await aqua_generate_for_offer(
        session,
        user,
        offer,
        listing_url=listing or None,
        price=(price or "").strip() or None,
        force_no_parse=True,
    )


@dataclass
class ReplyNotifyCtx:
    anchor_message_id: int
    to_email: str
    account_email: str
    incoming_from: str
    body_text: str
    is_preset: bool = False
    is_html: bool = False
    is_link: bool = False
    inbox_label: str | None = None
    html_attachment: str | None = None
    html_filename: str | None = None
    cleanup_message_ids: list[int] = field(default_factory=list)


def _preview_reply_body(body: str, *, is_html: bool = False, max_len: int = 220) -> str:
    t = (body or "").strip()
    if is_html:
        t = _strip_html(t) or "HTML-письмо"
    t = re.sub(r"\s+", " ", t).strip()
    if len(t) > max_len:
        return t[: max_len - 1] + "…"
    return t


async def _delete_message_safe(bot, chat_id: int, message_id: int | None) -> None:
    if not message_id:
        return
    try:
        await bot.delete_message(chat_id=int(chat_id), message_id=int(message_id))
    except Exception:
        pass


def _resolve_mail_anchor(
    acc_id: int,
    uid: str,
    meta: dict | None,
    callback_message: Message | None,
) -> int | None:
    """ID карточки входящего в Telegram (для reply_to)."""
    if callback_message and getattr(callback_message, "message_id", None):
        return int(callback_message.message_id)
    m = meta or {}
    anchor = m.get("tg_card_message_id")
    if anchor:
        return int(anchor)
    fm = FULL_META.get((int(acc_id), str(uid))) or {}
    anchor = fm.get("tg_card_message_id")
    if anchor:
        return int(anchor)
    return None


async def _notify_reply_sent(bot, chat_id: int, ctx: ReplyNotifyCtx) -> None:
    for mid in ctx.cleanup_message_ids:
        await _delete_message_safe(bot, chat_id, mid)

    from_acc = _e(ctx.account_email or "—")
    to_addr = _e(ctx.to_email or "—")
    anchor = int(ctx.anchor_message_id)

    kind = ""
    if ctx.is_html:
        kind = " [HTML]"
    elif ctx.is_preset:
        kind = " [пресет]"

    main = (
        f"{html_emoji('burst')} <b>Ответ{kind} — успешно отправлен на</b> "
        f"<code>{to_addr}</code> <b>с аккаунта</b> <code>{from_acc}</code> "
        f"{html_emoji('burst')}"
    )

    try:
        await bot.send_message(
            int(chat_id),
            main,
            parse_mode="HTML",
            reply_to_message_id=anchor,
        )
    except Exception:
        await bot.send_message(int(chat_id), main, parse_mode="HTML")

    try:
        await _try_pin(bot, int(chat_id), anchor)
    except Exception:
        pass

    if ctx.is_html and ctx.html_attachment:
        fname = (ctx.html_filename or "reply.html").strip() or "reply.html"
        if not fname.lower().endswith((".html", ".htm")):
            fname = f"{fname}.html"
        try:
            doc = BufferedInputFile(
                ctx.html_attachment.encode("utf-8"),
                filename=fname,
            )
            try:
                await bot.send_document(
                    int(chat_id),
                    doc,
                    caption=f"{html_emoji('presets')} HTML, который был отправлен",
                    reply_to_message_id=anchor,
                )
            except Exception:
                await bot.send_document(
                    int(chat_id),
                    doc,
                    caption=f"{html_emoji('presets')} HTML, который был отправлен",
                )
        except Exception:
            logger.exception(
                "Failed to attach sent HTML file chat=%s fname=%s bytes=%s",
                chat_id,
                fname,
                len(ctx.html_attachment or ""),
            )
    elif ctx.is_html and not ctx.html_attachment:
        logger.warning(
            "HTML reply notify without attachment to=%s from=%s",
            ctx.to_email,
            ctx.account_email,
        )

    # Короткое подтверждение — только если нужен отдельный toast (ссылка и т.д.)
    if ctx.is_link:
        footer = msg_ok("Ссылка создана")
        try:
            await bot.send_message(
                int(chat_id),
                footer,
                reply_to_message_id=anchor,
                parse_mode="HTML",
            )
        except Exception:
            await bot.send_message(int(chat_id), footer, parse_mode="HTML")


def _reply_notify_from_state(
    data: dict,
    *,
    body_text: str,
    is_preset: bool = False,
    is_html: bool = False,
    extra_cleanup: list[int] | None = None,
    meta: dict | None = None,
    acc_id: int | None = None,
    uid: str | None = None,
) -> ReplyNotifyCtx | None:
    return _reply_notify_build(
        acc_id=int(acc_id or data.get("acc_id") or 0),
        uid=str(uid or data.get("uid") or ""),
        meta=meta or {},
        state_data=data,
        body_text=body_text,
        is_preset=is_preset,
        is_html=is_html,
        extra_cleanup=extra_cleanup,
    )


def _reply_notify_build(
    *,
    acc_id: int,
    uid: str,
    meta: dict,
    state_data: dict,
    body_text: str,
    is_preset: bool = False,
    is_html: bool = False,
    extra_cleanup: list[int] | None = None,
) -> ReplyNotifyCtx | None:
    """Собрать уведомление об ответе: FSM + FULL_META (переживает рестарт/деплой)."""
    anchor = state_data.get("anchor_message_id") or meta.get("tg_card_message_id")
    if not anchor and acc_id and uid:
        anchor = (FULL_META.get((int(acc_id), str(uid))) or {}).get("tg_card_message_id")
    if not anchor:
        return None

    to_email = (
        state_data.get("to_email")
        or meta.get("from_email")
        or (FULL_META.get((int(acc_id), str(uid))) or {}).get("from_email")
        or ""
    )
    account_email = (
        state_data.get("account_email")
        or meta.get("account_email")
        or (FULL_META.get((int(acc_id), str(uid))) or {}).get("account_email")
        or ""
    )

    cleanup: list[int] = []
    ui = state_data.get("ui_message_id")
    if ui:
        cleanup.append(int(ui))
    if extra_cleanup:
        for mid in extra_cleanup:
            if mid and int(mid) not in cleanup:
                cleanup.append(int(mid))

    return ReplyNotifyCtx(
        anchor_message_id=int(anchor),
        to_email=_canon_email(str(to_email)),
        account_email=_canon_email(str(account_email)),
        incoming_from=_canon_email(str(to_email)),
        body_text=body_text,
        is_preset=is_preset,
        is_html=is_html,
        inbox_label=(state_data.get("inbox_label") or "").strip() or None,
        cleanup_message_ids=cleanup,
    )


async def _reply_notify_build_async(
    *,
    acc_id: int,
    uid: str,
    meta: dict,
    state_data: dict,
    body_text: str,
    is_preset: bool = False,
    is_html: bool = False,
    extra_cleanup: list[int] | None = None,
    user_id: int | None = None,
) -> ReplyNotifyCtx | None:
    """Как _reply_notify_build + fallback на ConversationLink.tg_message_id."""
    merged_state = dict(state_data)
    if acc_id and uid:
        try:
            async with Session() as session:
                to_e, subj, acc_e = await _resolve_reply_recipient(
                    session,
                    int(acc_id),
                    str(uid),
                    meta=meta,
                    state_data=state_data,
                    mail_id=state_data.get("mail_id"),
                )
            if to_e:
                merged_state.setdefault("to_email", to_e)
            if subj:
                merged_state.setdefault("subject", subj)
            if acc_e:
                merged_state.setdefault("account_email", acc_e)
        except Exception:
            pass

    ctx = _reply_notify_build(
        acc_id=acc_id,
        uid=uid,
        meta=meta,
        state_data=merged_state,
        body_text=body_text,
        is_preset=is_preset,
        is_html=is_html,
        extra_cleanup=extra_cleanup,
    )
    if ctx:
        return ctx

    inbox = _canon_email(str(meta.get("account_email") or state_data.get("account_email") or ""))
    contact = _canon_email(str(meta.get("from_email") or state_data.get("to_email") or ""))
    if not user_id or not inbox or not contact:
        return None

    try:
        async with Session() as session:
            conv = await _load_convlink_for_reply(session, user_id=int(user_id), inbox_email=inbox, contact_email=contact)
        if conv and getattr(conv, "tg_message_id", None):
            return ReplyNotifyCtx(
                anchor_message_id=int(conv.tg_message_id),
                to_email=contact,
                account_email=inbox,
                incoming_from=contact,
                body_text=body_text,
                is_preset=is_preset,
                is_html=is_html,
                cleanup_message_ids=list(extra_cleanup or []),
            )
    except Exception:
        pass
    return None


async def _load_convlink_for_reply(session, *, user_id: int, inbox_email: str, contact_email: str):
    inbox_keys = _email_keys(inbox_email)
    contact_keys = _email_keys(contact_email)
    if not inbox_keys or not contact_keys:
        return None
    return (
        await session.execute(
            sa_select(ConversationLink)
            .where(ConversationLink.user_id == int(user_id))
            .where(func.lower(ConversationLink.account_email).in_(inbox_keys))
            .where(func.lower(ConversationLink.from_email).in_(contact_keys))
            .order_by(ConversationLink.id.desc())
            .limit(1)
        )
    ).scalars().first()


async def _ensure_mailing_proxy_for_send(message_or_cb, tg_id: int) -> bool:
    """Без прокси SMTP не стартует — ни рассылка, ни ответы."""
    try:
        async with Session() as session:
            user = await get_or_create_user(session, tg_id)
            if await user_has_active_mailing_proxy(session, int(user.id)):
                return True
    except Exception:
        logger.exception("proxy preflight failed tg=%s", tg_id)
        return False

    text = f"{html_emoji('fail')} Нет прокси. Добавь SOCKS5 или HTTP в {menu_path(('settings', ''), ('proxy', 'Прокси'))}."
    if isinstance(message_or_cb, CallbackQuery):
        try:
            await message_or_cb.answer(text, show_alert=True)
        except Exception:
            pass
    else:
        await message_or_cb.answer(text)
    return False


async def _bg_incoming_smtp(
    callback: CallbackQuery,
    user_id: int,
    coro_fn,
    *,
    notify: ReplyNotifyCtx | None = None,
    notify_builder=None,
) -> bool:
    """SMTP в фоне — polling не блокируется. Только через прокси."""
    if not await _ensure_mailing_proxy_for_send(callback, user_id):
        return False
    try:
        await callback.answer(toast("wait", "Отправляю…"), show_alert=False)
    except Exception:
        pass
    if bg_is_running(user_id, "smtp"):
        try:
            await callback.answer(toast("wait", "Отправка уже идёт…"), show_alert=True)
        except Exception:
            pass
        return False

    chat_id = callback.message.chat.id
    bot = callback.bot

    async def _job() -> None:
        try:
            ok, err, _msgid = await asyncio.wait_for(
                coro_fn(), timeout=_incoming_smtp_wait_sec() + 10
            )
        except asyncio.TimeoutError:
            ok, err = False, (
                f"Timeout: SMTP отправка > {_incoming_smtp_wait_sec()}с "
                f"(прокси перебираются, подождите или уменьшите число прокси)"
            )
        except Exception as e:
            ok, err = False, f"{type(e).__name__}: {e}"
        if ok:
            ctx = notify
            if notify_builder:
                try:
                    ctx = await notify_builder()
                except Exception:
                    pass
            if ctx:
                await _notify_reply_sent(bot, chat_id, ctx)
            else:
                await bot.send_message(chat_id, f"{html_emoji('ok')} Отправлено.", parse_mode="HTML")
        else:
            err_s = _e(_smtp_user_error(err or "unknown"))
            await bot.send_message(chat_id, f"{html_emoji('fail')} Ошибка SMTP:\n<code>{err_s}</code>", parse_mode="HTML")

    if not bg_start(user_id, "smtp", _job()):
        try:
            await callback.answer(toast("wait", "Отправка уже идёт…"), show_alert=True)
        except Exception:
            pass
        return False
    return True


async def _bg_message_smtp(
    message: Message,
    user_id: int,
    coro_fn,
    *,
    notify: ReplyNotifyCtx | None = None,
    notify_builder=None,
) -> bool:
    """SMTP из текстового ответа — в фоне. Только через прокси."""
    if not await _ensure_mailing_proxy_for_send(message, user_id):
        return False
    if bg_is_running(user_id, "smtp"):
        await message.answer(f"{html_emoji('wait')} Отправка уже идёт…")
        return False

    chat_id = message.chat.id
    bot = message.bot

    async def _job() -> None:
        try:
            ok, err, _msgid = await asyncio.wait_for(
                coro_fn(), timeout=_incoming_smtp_wait_sec() + 10
            )
        except asyncio.TimeoutError:
            ok, err = False, (
                f"Timeout: SMTP отправка > {_incoming_smtp_wait_sec()}с "
                f"(прокси перебираются, подождите или уменьшите число прокси)"
            )
        except Exception as e:
            ok, err = False, f"{type(e).__name__}: {e}"
        if ok:
            ctx = notify
            if notify_builder:
                try:
                    ctx = await notify_builder()
                except Exception:
                    pass
            if ctx:
                await _notify_reply_sent(bot, chat_id, ctx)
            else:
                await bot.send_message(chat_id, f"{html_emoji('ok')} Отправлено.", parse_mode="HTML")
        else:
            err_s = _e(_smtp_user_error(err or "unknown"))
            await bot.send_message(chat_id, f"{html_emoji('fail')} Ошибка SMTP:\n<code>{err_s}</code>", parse_mode="HTML")

    if not bg_start(user_id, "smtp", _job()):
        await message.answer(f"{html_emoji('wait')} Отправка уже идёт…")
        return False
    return True


class _MailReplyState(StatesGroup):
    # after clicking "Написать ещё" we show a choice menu (preset / HTML / manual)
    waiting_choice = State()
    waiting_text = State()
    waiting_custom_html = State()


def _is_primary_mail_reply_cb(data: str | None) -> bool:
    """Только mail_reply:acc:uid — не mail_reply_mode / mail_reply_html / mail_reply_db."""
    d = (data or "").strip()
    return d.startswith("mail_reply:") and d.split(":", 1)[0] == "mail_reply"


def _kb_reply_choice(acc_id: int, uid: str):
    from aiogram.types import InlineKeyboardMarkup

    uid_s = str(uid)
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                inline_button(
                    "presets",
                    "Отправить пресет",
                    callback_data=f"mail_reply_mode:preset:{acc_id}:{uid_s}",
                ),
                inline_button(
                    "puzzle",
                    "Отправить HTML",
                    callback_data=f"mail_reply_mode:html:{acc_id}:{uid_s}",
                ),
            ],
            [
                inline_button(
                    "cancel",
                    "Отмена",
                    callback_data=f"mail_reply_mode:cancel:{acc_id}:{uid_s}",
                )
            ],
        ]
    )


async def _open_mail_reply_menu(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    acc_id: int,
    uid: str,
    mail_id: int | None = None,
) -> None:
    """Меню ответа — отдельное сообщение. Карточку письма не трогаем (кнопки остаются)."""
    from database import db_session

    uid_key = str(uid)
    meta: dict = dict(FULL_META.get((acc_id, uid_key)) or {})
    card_html = ""
    if callback.message:
        card_html = callback.message.html_text or callback.message.text or ""

    async with db_session() as session:
        to_email, subject, account_email = await _resolve_reply_recipient(
            session,
            acc_id,
            uid_key,
            meta=meta,
            state_data={},
            mail_id=int(mail_id) if mail_id else None,
            card_html=card_html,
        )
        if mail_id:
            mail_row = await _load_incoming_mail_by_id(session, int(mail_id))
            if mail_row:
                acc_id = int(mail_row.account_id)
                uid_key = str(mail_row.imap_uid)

        inbox_label = ""
        try:
            user = await get_or_create_user(session, int(callback.from_user.id))
            inbox_label = (getattr(user, "sender_name", None) or "").strip()
        except Exception:
            pass

    from services.email_address import is_valid_smtp_recipient

    if not is_valid_smtp_recipient(to_email):
        await callback.answer(
            "Не вижу email получателя. Загрузите VOID+валидацию или откройте свежее письмо.",
            show_alert=True,
        )
        return

    fm = dict(FULL_META.get((acc_id, uid_key)) or meta)
    fm.update(
        {
            "from_email": to_email,
            "subject": subject,
            "account_email": account_email,
            "tg_card_message_id": int(callback.message.message_id) if callback.message else None,
        }
    )
    if mail_id:
        fm["_mail_id"] = int(mail_id)
    try:
        if mail_id:
            async with db_session() as s2:
                mrow = await _load_incoming_mail_by_id(s2, int(mail_id))
                if mrow:
                    mid = (getattr(mrow, "rfc_message_id", None) or "").strip()
                    if mid:
                        fm["rfc_message_id"] = mid
                    irt = (getattr(mrow, "rfc_in_reply_to", None) or "").strip()
                    if irt:
                        fm["rfc_in_reply_to"] = irt
                    refs = (getattr(mrow, "rfc_references", None) or "").strip()
                    if refs:
                        fm["rfc_references"] = refs
    except Exception:
        pass
    FULL_META[(acc_id, uid_key)] = fm

    await state.set_state(_MailReplyState.waiting_choice)
    kb = _kb_reply_choice(acc_id, uid_key)
    card = callback.message
    anchor_id = int(card.message_id) if card else None

    ui_message_id: int | None = None
    if not card:
        await callback.answer("Нет сообщения для ответа", show_alert=True)
        return

    try:
        ui = await tg_call(
            lambda: callback.bot.send_message(
                int(card.chat.id),
                (
                    f"<b>{html_emoji('mail')} Ответ на письмо</b>\n"
                    f"Кому: <code>{_e(to_email)}</code>\n\n"
                    f"{REPLY_CHOICE_TEXT}"
                ),
                reply_markup=kb,
                parse_mode="HTML",
                reply_to_message_id=anchor_id,
            )
        )
        ui_message_id = int(ui.message_id)
    except Exception as e:
        logger.exception("mail_reply send_menu failed acc=%s uid=%s", acc_id, uid_key)
        await callback.answer(
            "Телеграм временно лимитирует сообщения. Подожди пару секунд и нажми ещё раз.",
            show_alert=True,
        )
        return

    await state.update_data(
        acc_id=acc_id,
        uid=uid_key,
        mail_id=int(mail_id) if mail_id else None,
        to_email=to_email,
        subject=subject,
        account_email=account_email,
        anchor_message_id=anchor_id,
        ui_message_id=ui_message_id,
        inbox_label=inbox_label,
    )
    await callback.answer()


def _kb_preset_pick(
    items: list[TemplateItem],
    acc_id: int,
    uid: str,
    *,
    mail_id: int | None = None,
):
    """Picker for reply-presets.

    IMPORTANT (per TZ): must use the same presets as ⚡ Шаблоны.
    We reuse handlers/templates.py storage and send via the existing mail_tmpl_send handler.
    """
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

    rows: list[list[InlineKeyboardButton]] = []

    for i, t in enumerate(items[:30]):
        label = (t.title or f"Пресет #{i + 1}").strip()[:40]
        if mail_id:
            cb = f"mail_tmpl_send:{i}:m{int(mail_id)}"
        else:
            cb = f"mail_tmpl_send:{i}:{acc_id}:{uid}"
        rows.append([InlineKeyboardButton(text=label, callback_data=cb)])

    rows.append([back_inline(f"mail_reply_mode:back:{acc_id}:{uid}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _kb_html_pick(acc_id: int, uid: str):
    """HTML picker (strict TZ): GO / GO(new) / PUSH / SMS / BACK."""
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                inline_button("green", "GO", callback_data=f"mail_reply_html:go:{acc_id}:{uid}"),
                inline_button("green", "GO(new)", callback_data=f"mail_reply_html:go_new:{acc_id}:{uid}"),
            ],
            [inline_button("burst", "PUSH", callback_data=f"mail_reply_html:push:{acc_id}:{uid}")],
            [inline_button("write", "SMS", callback_data=f"mail_reply_html:sms:{acc_id}:{uid}")],
            [back_inline(f"mail_reply_html:back:{acc_id}:{uid}", text="BACK")],
            [inline_button("cancel", "Отмена", callback_data=f"mail_reply_mode:back:{acc_id}:{uid}")],
        ]
    )


@router.callback_query(F.data.startswith("mail_hide:"))
async def cb_mail_hide(callback: CallbackQuery):
    """Скрыть карточку письма (UI как в референс-видео).

    Безопасное поведение:
    - пытаемся снять pin (если был)
    - удаляем сообщение с карточкой
    """
    try:
        _, acc_id, uid = (callback.data or "").split(":", 2)
        int(acc_id)
        str(uid)
    except Exception:
        return await callback.answer("Неверные данные", show_alert=True)

    try:
        # best-effort unpin + delete
        try:
            await callback.bot.unpin_chat_message(chat_id=callback.message.chat.id, message_id=callback.message.message_id)
        except Exception:
            pass
        await callback.message.delete()
    except Exception:
        # если нельзя удалить — просто убираем клавиатуру
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass

    await callback.answer("Скрыто")


@router.callback_query(F.data.startswith("mail_ignore:"))
async def cb_mail_ignore(callback: CallbackQuery):
    """Отметить письмо как "не отвечать".

    В проекте авто-ответ запускается сразу после получения письма,
    поэтому здесь мы делаем честное и полезное действие:
    - убираем кнопки, чтобы не тыкали случайно
    - помечаем в FULL_META флагом ignored (на будущее/лог)
    """
    try:
        _, acc_id, uid = (callback.data or "").split(":", 2)
        acc_id_i = int(acc_id)
        uid_s = str(uid)
    except Exception:
        return await callback.answer("Неверные данные", show_alert=True)

    try:
        meta = FULL_META.get((acc_id_i, uid_s)) or {}
        meta["ignored"] = True
        FULL_META[(acc_id_i, uid_s)] = meta
    except Exception:
        pass

    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    await callback.answer("Ок")


def _canon_email(email: str) -> str:
    from services.email_address import canonicalize_dialog_email

    return canonicalize_dialog_email(email)


def _email_keys(email: str) -> list[str]:
    from services.email_address import dialog_email_match_keys

    return dialog_email_match_keys(email)


_LOT_ID_FROM_CARD_RE = re.compile(
    r"Лот:\s*(?:</b>\s*)?<code>\s*(\d+)\s*</code>",
    re.IGNORECASE,
)


def _offer_id_from_incoming_card_message(message: Message | None) -> int | None:
    """Лот с HTML-карточки Telegram (кнопка «Создать ссылку» на том же сообщении)."""
    if not message:
        return None
    raw = (getattr(message, "html_text", None) or message.text or "") or ""
    m = _LOT_ID_FROM_CARD_RE.search(raw)
    if not m:
        return None
    try:
        return int(m.group(1))
    except (TypeError, ValueError):
        return None


async def _sync_incoming_mail_offer_with_card(
    session,
    mail: IncomingMail,
    *,
    tg_message: Message | None = None,
) -> None:
    """Подтянуть лот как на карточке (meta + «Лот:» в тексте), записать в IncomingMail."""
    from services.incoming_mail_worker import mail_card_offer_meta
    from services.offer_storage import live_user_offer, normalize_incoming_seller_email

    uid = int(getattr(mail, "user_id", 0) or 0)
    card_oid = _offer_id_from_incoming_card_message(tg_message)
    if card_oid:
        live = await live_user_offer(session, user_id=uid, offer_id=int(card_oid))
        if live:
            mail.resolved_offer_id = int(live.id)
            mail.mailing_bound = True
        elif getattr(mail, "resolved_offer_id", None) and int(mail.resolved_offer_id) == int(card_oid):
            mail.resolved_offer_id = None

    contact = normalize_incoming_seller_email(getattr(mail, "from_email", "") or "") or (
        getattr(mail, "from_email", "") or ""
    ).strip()
    if not contact:
        return

    try:
        (
            offer_id,
            service_label,
            product_title,
            photo_url,
            offer_price,
            outgoing_subj,
        ) = await mail_card_offer_meta(
            session,
            user_id=int(mail.user_id),
            from_email=contact,
            resolved_offer_id=getattr(mail, "resolved_offer_id", None),
            ad_url=(getattr(mail, "ad_url", "") or "").strip() or None,
            inbox_email=(getattr(mail, "account_email", "") or "").strip() or None,
            subject=(getattr(mail, "subject", "") or "").strip(),
            from_name=(getattr(mail, "from_name", "") or "").strip(),
            body_text=(getattr(mail, "body", "") or "").strip(),
            stored_product_title=(getattr(mail, "product_title", None) or "").strip() or None,
            stored_offer_price=(getattr(mail, "offer_price", None) or "").strip() or None,
            stored_photo_url=(getattr(mail, "photo_url", None) or "").strip() or None,
            stored_service_label=(getattr(mail, "service_label", None) or "").strip() or None,
            stored_outgoing_subject=(getattr(mail, "outgoing_mail_subject", None) or "").strip() or None,
            mailing_bound=True,
        )
    except Exception:
        logger.exception("sync incoming mail offer with card meta failed mail_id=%s", getattr(mail, "id", None))
        try:
            await session.rollback()
        except Exception:
            pass
        return

    if offer_id:
        live_meta = await live_user_offer(session, user_id=uid, offer_id=int(offer_id))
        if live_meta:
            mail.resolved_offer_id = int(live_meta.id)
            mail.mailing_bound = True
        else:
            mail.resolved_offer_id = None
    if product_title:
        mail.product_title = (product_title or "")[:500]
    if offer_price:
        mail.offer_price = (offer_price or "")[:120]
    if photo_url:
        mail.photo_url = (photo_url or "")[:2000]
    if service_label:
        mail.service_label = (service_label or "")[:80]
    if outgoing_subj:
        mail.outgoing_mail_subject = (outgoing_subj or "")[:500]
    await _flush_incoming_mail_bind(session, mail, user_id=uid)


async def _flush_incoming_mail_bind(session, mail: IncomingMail, *, user_id: int) -> None:
    """Не ронять сессию FK на удалённый лот: сначала проверить, иначе обнулить."""
    from services.offer_storage import live_user_offer

    oid = getattr(mail, "resolved_offer_id", None)
    if oid:
        live = await live_user_offer(session, user_id=int(user_id), offer_id=int(oid))
        if not live:
            mail.resolved_offer_id = None
    try:
        await session.flush()
    except IntegrityError:
        logger.warning(
            "incoming_mail FK flush mail_id=%s oid=%s — drop bind",
            getattr(mail, "id", None),
            oid,
        )
        try:
            await session.rollback()
        except Exception:
            pass
        mail.resolved_offer_id = None


async def _bound_offer_from_incoming_mail(
    session,
    mail: IncomingMail,
    *,
    user_id: int,
) -> tuple[Offer | None, str]:
    """Лот уже на карточке (resolved_offer_id / snapshot) — не резолвить заново."""
    from services.offer_matching import _load_offer
    from services.offer_storage import (
        find_offer_for_mailed_seller_reply,
        normalize_incoming_seller_email,
        offer_effective_link,
    )

    uid = int(user_id)
    owner_id = int(getattr(mail, "user_id", 0) or 0)
    oid = getattr(mail, "resolved_offer_id", None)
    subj = (getattr(mail, "subject", "") or "").strip()
    body = (getattr(mail, "body", "") or "").strip()
    if oid:
        for uid_try in (owner_id, uid):
            if not uid_try:
                continue
            off = await _load_offer(session, user_id=int(uid_try), offer_id=int(oid))
            if off:
                from services.incoming_lead_resolve import inbound_thread_binds_offer

                if not inbound_thread_binds_offer(subj, body, off):
                    break
                url = (offer_effective_link(off) or "").strip()
                if not url:
                    url = (getattr(mail, "ad_url", "") or "").strip()
                return off, url

    contact = normalize_incoming_seller_email(getattr(mail, "from_email", "") or "") or (
        getattr(mail, "from_email", "") or ""
    ).strip()
    if contact and owner_id:
        from services.incoming_lead_resolve import resolve_offer_for_incoming_lead

        off_r, url_r, _how, _snap = await resolve_offer_for_incoming_lead(
            session,
            user_id=int(owner_id),
            contact_email=contact,
            subject=subj,
            body_text=body,
            inbox_email=(getattr(mail, "account_email", "") or "").strip() or None,
            resolved_offer_id=None,
        )
        if off_r:
            url = (url_r or offer_effective_link(off_r) or "").strip() or (
                getattr(mail, "ad_url", "") or ""
            ).strip()
            return off_r, url

    if contact and owner_id:
        from services.mailing_send_log import has_mailing_send_for_contact

        mailed = bool(getattr(mail, "mailing_bound", False)) or await has_mailing_send_for_contact(
            session, int(owner_id), contact
        )
        if mailed or (getattr(mail, "product_title", "") or "").strip():
            off = await find_offer_for_mailed_seller_reply(
                session,
                user_id=owner_id,
                contact_email=contact,
                subject=(getattr(mail, "subject", "") or "").strip(),
                body_text=(getattr(mail, "body", "") or "").strip(),
                inbox_email=(getattr(mail, "account_email", "") or "").strip(),
            )
            if off:
                url = (offer_effective_link(off) or "").strip() or (
                    getattr(mail, "ad_url", "") or ""
                ).strip()
                return off, url
    return None, ""


async def _resolve_and_bind_incoming_mail_offer(
    session,
    *,
    mail: IncomingMail,
    inbox_email: str,
) -> tuple[Offer | None, str]:
    """Лот по validated email (OfferEmail) → поля IncomingMail."""
    from services.incoming_lead_resolve import resolve_offer_for_incoming_lead
    from services.offer_storage import normalize_incoming_seller_email, offer_effective_link

    off_stored, url_stored = await _bound_offer_from_incoming_mail(
        session, mail, user_id=int(mail.user_id)
    )
    if off_stored:
        mail.resolved_offer_id = int(off_stored.id)
        mail.mailing_bound = True
        if url_stored:
            mail.ad_url = url_stored
        return off_stored, url_stored

    contact = normalize_incoming_seller_email(getattr(mail, "from_email", "") or "")
    if not contact:
        return None, ""

    off, url, _how, snap = await resolve_offer_for_incoming_lead(
        session,
        user_id=int(mail.user_id),
        contact_email=contact,
        subject=(getattr(mail, "subject", "") or "").strip(),
        from_name=(getattr(mail, "from_name", "") or "").strip(),
        body_text=(getattr(mail, "body", "") or "").strip(),
        resolved_offer_id=getattr(mail, "resolved_offer_id", None),
        inbox_email=(inbox_email or "").strip(),
        mailing_bound=bool(getattr(mail, "mailing_bound", False)),
    )
    if not off:
        return None, ""
    url = (url or "").strip() or (offer_effective_link(off) or "").strip()
    mail.resolved_offer_id = int(off.id)
    mail.mailing_bound = True
    if url:
        mail.ad_url = url
    pt = (snap.get("product_title") or "").strip()
    if pt:
        mail.product_title = pt[:500]
    pr = (snap.get("offer_price") or "").strip()
    if pr:
        mail.offer_price = pr[:64]
    ph = (snap.get("photo_url") or "").strip()
    if ph:
        mail.photo_url = ph[:2000]
    sl = (snap.get("service_label") or "").strip()
    if sl:
        mail.service_label = sl[:64]
    return off, url


async def _aqua_last_chance_offer_url(
    session,
    *,
    user_id: int,
    mail: IncomingMail | None,
    inbox_email: str,
    contact_email: str,
    resolved_id: int | None,
    subject: str = "",
    body_text: str = "",
) -> tuple[Offer | None, str]:
    """OfferEmail / pin (если тема = OFFER) — перед «не нашёл объявление»."""
    from services.offer_matching import (
        _load_conversation_link,
        _load_offer,
        incoming_subject_binds_offer,
        subject_is_informative,
    )
    from services.offer_storage import find_single_offer_for_seller_contact_email, offer_effective_link

    subj = (subject or "").strip()
    subj_strong = subject_is_informative(subj)

    conv = await _load_conversation_link(
        session,
        user_id=int(user_id),
        inbox_email=(inbox_email or "").strip(),
        contact_email=(contact_email or "").strip(),
    )
    if conv and getattr(conv, "pinned_offer_id", None):
        off = await _load_offer(
            session, user_id=int(user_id), offer_id=int(conv.pinned_offer_id)
        )
        if off and incoming_subject_binds_offer(subj, off):
            url = (offer_effective_link(off) or "").strip() or (
                getattr(conv, "ad_url", "") or ""
            ).strip()
            return off, url

    off = await find_single_offer_for_seller_contact_email(
        session,
        user_id=int(user_id),
        contact_email=contact_email,
        subject=subj,
        body_text=body_text or "",
    )
    if off:
        url = (offer_effective_link(off) or "").strip()
        return off, url

    from services.offer_storage import find_offer_for_mailed_seller_reply

    off_fi = await find_offer_for_mailed_seller_reply(
        session,
        user_id=int(user_id),
        contact_email=contact_email,
        subject=subj,
        body_text=body_text or "",
        inbox_email=(inbox_email or "").strip(),
    )
    if off_fi:
        url = (offer_effective_link(off_fi) or "").strip()
        return off_fi, url

    oid = resolved_id or (int(mail.resolved_offer_id) if mail and mail.resolved_offer_id else None)
    if oid:
        off = await _load_offer(session, user_id=int(user_id), offer_id=int(oid))
        if off:
            url = (offer_effective_link(off) or "").strip()
            if not url and mail:
                url = (getattr(mail, "ad_url", "") or "").strip()
            return off, url
    return None, ""


async def _aqua_resolve_pins_for_mail(
    session,
    *,
    user_id: int,
    subject: str,
    resolved_offer_id: int | None,
    mailing_bound: bool,
    inbox_email: str = "",
    contact_email: str = "",
) -> tuple[int | None, bool]:
    """Не сбрасываем лот по теме Aw:/Re: — pin только если тема = OFFER или короткий ответ."""
    from services.offer_matching import _load_conversation_link, _load_offer, incoming_subject_binds_offer, subject_is_informative

    oid = int(resolved_offer_id) if resolved_offer_id else None
    bound = bool(mailing_bound)
    inbox = (inbox_email or "").strip().lower()
    contact = (contact_email or "").strip().lower()
    subj_strong = subject_is_informative((subject or "").strip())
    if inbox and contact:
        conv = await _load_conversation_link(
            session,
            user_id=int(user_id),
            inbox_email=inbox,
            contact_email=contact,
        )
        if conv and getattr(conv, "pinned_offer_id", None):
            pin_oid = int(conv.pinned_offer_id)
            off_pin = await _load_offer(session, user_id=int(user_id), offer_id=pin_oid)
            if off_pin and (
                not subj_strong or incoming_subject_binds_offer(subject or "", off_pin)
            ):
                oid = pin_oid
                bound = True
    return oid, bound


def _parse_imap_uid_key(uid: str) -> int | None:
    uid_s = (uid or "").strip()
    if ":" in uid_s:
        uid_s = uid_s.rsplit(":", 1)[-1]
    try:
        return int(uid_s)
    except (TypeError, ValueError):
        return None


async def _load_incoming_mail_for_uid(session, acc_id: int, uid: str) -> IncomingMail | None:
    uid_num = _parse_imap_uid_key(uid)
    if uid_num is None:
        return None
    return (
        await session.execute(
            sa_select(IncomingMail)
            .where(IncomingMail.account_id == int(acc_id))
            .where(IncomingMail.imap_uid == int(uid_num))
            .order_by(IncomingMail.id.desc())
            .limit(1)
        )
    ).scalars().first()


async def _load_incoming_mail_for_callback(
    session,
    *,
    acc_id: int | None = None,
    uid: str | None = None,
    tg_message_id: int | None = None,
) -> IncomingMail | None:
    """Письмо для кнопок на карточке: acc+uid, иначе id сообщения Telegram."""
    if acc_id and uid:
        mail = await _load_incoming_mail_for_uid(session, int(acc_id), str(uid))
        if mail:
            return mail
    if tg_message_id:
        return (
            await session.execute(
                sa_select(IncomingMail)
                .where(IncomingMail.telegram_message_id == int(tg_message_id))
                .order_by(IncomingMail.id.desc())
                .limit(1)
            )
        ).scalars().first()
    return None


async def _load_incoming_mail_by_id(session, mail_id: int) -> IncomingMail | None:
    try:
        mid = int(mail_id)
    except (TypeError, ValueError):
        return None
    return (
        await session.execute(
            sa_select(IncomingMail).where(IncomingMail.id == mid).limit(1)
        )
    ).scalars().first()


def _meta_from_incoming_mail(mail: IncomingMail) -> dict:
    return {
        "from_email": (mail.from_email or "").strip(),
        "from_name": (mail.from_name or "").strip(),
        "subject": mail.subject or "",
        "account_email": (mail.account_email or "").strip(),
        "date_str": mail.date_str or "",
        "rfc_message_id": (getattr(mail, "rfc_message_id", None) or "").strip(),
        "rfc_in_reply_to": (getattr(mail, "rfc_in_reply_to", None) or "").strip(),
        "rfc_references": (getattr(mail, "rfc_references", None) or "").strip(),
    }


def _extract_sender_email_from_mail_card_html(
    card_html: str,
    *,
    account_email: str = "",
) -> str:
    """Email продавца из шапки карточки (не из цитаты в «Текст»)."""
    raw = (card_html or "").strip()
    if not raw:
        return ""
    # Тело в <blockquote> — там цитаты с чужими From; не парсим.
    head = re.split(r"(?i)<b>\s*Тема\s*:</b>", raw, maxsplit=1)[0]
    acc = _canon_email(account_email)
    for chunk in re.findall(r"<code>([^<]+)</code>", head, flags=re.I):
        em = _canon_email(html.unescape(chunk))
        if em and "@" in em and em != acc:
            return em
    plain = html.unescape(re.sub(r"<[^>]+>", " ", head))
    from services.email_address import extract_email_address

    for part in plain.split():
        em = _canon_email(part)
        if em and "@" in em and em != acc:
            return em
    return _canon_email(extract_email_address(plain))


async def _offer_email_for_resolved_offer(session, offer_id: int | None) -> str:
    if not offer_id:
        return ""
    row = (
        await session.execute(
            sa_select(OfferEmail.email)
            .where(OfferEmail.offer_id == int(offer_id))
            .order_by(OfferEmail.id.asc())
            .limit(1)
        )
    ).first()
    if row and row[0]:
        return _canon_email(str(row[0]))
    return ""


async def _resolve_reply_recipient(
    session,
    acc_id: int,
    uid: str,
    *,
    meta: dict | None = None,
    state_data: dict | None = None,
    mail_id: int | None = None,
    card_html: str | None = None,
) -> tuple[str, str, str]:
    """
    Email получателя ответа (контакт), тема, наш ящик.
    Источник правды — IncomingMail в Postgres (переживает redeploy).
    """
    meta = dict(meta or {})
    state_data = state_data or {}

    to_email = _canon_email(
        state_data.get("to_email") or meta.get("from_email") or ""
    )
    subject = (state_data.get("subject") or meta.get("subject") or "").strip()
    account_email = _canon_email(
        state_data.get("account_email") or meta.get("account_email") or ""
    )

    mail: IncomingMail | None = None
    if mail_id:
        mail = await _load_incoming_mail_by_id(session, int(mail_id))
        if mail:
            acc_id = int(mail.account_id)
            uid = str(mail.imap_uid)
            meta = {**meta, **_meta_from_incoming_mail(mail)}

    if not mail:
        mail = await _load_incoming_mail_for_uid(session, acc_id, uid)

    if mail:
        to_email = _canon_email(mail.from_email or "") or to_email
        subject = (mail.subject or "").strip() or subject
        account_email = _canon_email(mail.account_email or "") or account_email
        if not to_email:
            to_email = await _offer_email_for_resolved_offer(
                session, getattr(mail, "resolved_offer_id", None)
            )

    if not to_email:
        fm = FULL_META.get((int(acc_id), str(uid))) or {}
        to_email = _canon_email(fm.get("from_email") or "") or to_email
        subject = subject or (fm.get("subject") or "").strip()
        account_email = account_email or _canon_email(fm.get("account_email") or "")

    if not account_email:
        acc = await session.get(EmailAccount, int(acc_id))
        if acc and acc.email:
            account_email = _canon_email(acc.email)

    if not to_email and card_html:
        to_email = _extract_sender_email_from_mail_card_html(
            card_html, account_email=account_email
        )

    if to_email:
        fm_key = (int(acc_id), str(uid))
        FULL_META[fm_key] = {
            **(FULL_META.get(fm_key) or {}),
            "from_email": to_email,
            "subject": subject,
            "account_email": account_email,
        }

    return to_email, subject, account_email


def _e(s: str) -> str:
    return html.escape(s or "", quote=False)


def _smtp_user_error(err: str | None) -> str:
    raw = (err or "unknown").strip()
    blob = raw.lower()
    if (
        "smtpserverdisconnected" in blob
        or "connection unexpectedly closed" in blob
        or ":disconnect:" in blob
        or "disconnect|" in blob
    ):
        return (
            "Gmail оборвал SMTP через прокси. "
            "Проверьте прокси и нажмите пресет ещё раз."
        )
    return raw[:350]


def _clean(v: str | None) -> str:
    return (v or "").strip()


def _service_label_for_card(service_code: str) -> str:
    """Human-readable service label for the link card."""
    sc = (service_code or "").strip()
    low = sc.lower()
    if low in {"facebook", "facebook.com"}:
        return "facebook.com"
    if low in {"olx_pt", "olx.pt"}:
        return "OLX.pt"
    if low in {"jofogas_hu", "jofogas.hu", "jofogas"}:
        return "Jófogás"
    if low in {"njuskalo_hr", "njuskalo.hr", "njuskalo"}:
        return "Njuškalo"
    if "_" in low and low.split("_", 1)[0] == "olx":
        cc = low.split("_", 1)[-1]
        return f"OLX.{cc}" if cc and cc != "pt" else "OLX.pt"
    return sc or "—"


def _generate_card_service_label(*, team_id: str, service_code: str, offer) -> str:
    """На карточке ссылки — площадка генерации (OLX), не домен лота (marktplaats)."""
    tid = (team_id or "").strip().lower()
    sc = (service_code or "").strip()
    if tid == "csm" and sc:
        from services.csm_catalog import parse_service_key, platform_label

        plat, cc = parse_service_key(sc)
        if plat == "olx":
            return "OLX.pt" if cc == "pt" else f"OLX.{cc or 'pt'}"
        if plat == "jofogas":
            return "Jófogás"
        if plat == "njuskalo":
            return "Njuškalo"
        if plat:
            host = f"{platform_label(plat)}"
            if cc:
                return f"{host} ({cc.upper()})"
            return host
        return _service_label_for_card(sc)
    if tid in {"hustle", "bastard", "rpc"} and sc:
        if tid == "rpc":
            from services.rpc_catalog import rpc_service_label

            return rpc_service_label(sc)
        if tid == "bastard":
            from services.bastard_catalog import bastard_service_label

            return bastard_service_label(sc)
        from services.hustle_catalog import hustle_service_label

        return hustle_service_label(sc)
    from services.offer_storage import marketplace_service_label_from_offer

    return marketplace_service_label_from_offer(offer) or _service_label_for_card(sc)


async def _send_generated_link_card_to_chat(
    bot,
    chat_id: int,
    *,
    offer_title: str | None,
    offer_price: str | None,
    photo_url: str | None,
    profile_display: str | None,
    service_code: str,
    link: str,
    offer_id: int | None = None,
    anchor_message_id: int | None = None,
    account_email: str | None = None,
    contact_email: str | None = None,
    inbox_label: str | None = None,
):
    """Карточка AQUA-ссылки — reply к исходному письму (как пресет/HTML)."""
    service_label = _service_label_for_card(service_code)
    reply_to = int(anchor_message_id) if anchor_message_id else None

    from_acc = _e((account_email or "").strip() or "—")
    to_addr = _e((contact_email or "").strip() or "—")
    head = ""
    if reply_to:
        # Не дублируем «Получено сообщение на …» — это уже в карточке входящего (reply_to).
        head = (
            f"{html_emoji('burst')} <code>{from_acc}</code> — <b>ссылка создана</b> — <code>{to_addr}</code>\n"
            f"От кого было входящее: <code>{to_addr}</code>\n\n"
        )

    card_text = (
        f"{head}"
        f"{html_emoji('burst')} <b>Объявления » {_e(service_label)}</b>\n\n"
        f"{html_emoji('pin')} <b>{_e((offer_title or '').strip()) or '—'}</b>\n"
        f"{html_emoji('price')} <b>Цена:</b> {_e((offer_price or '').strip()) or '—'} {html_emoji('price')}\n"
        f"{html_emoji('user')} <b>Профиль:</b> <code>{_e((profile_display or '').strip()) or '—'}</code>\n\n"
        f"{html_emoji('link')} <b>Ссылка:</b>\n{_e(link)}"
    )

    price_kb = None
    if offer_id:
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

        price_kb = InlineKeyboardMarkup(
            inline_keyboard=[[inline_button("edit", "Цена", callback_data=f"offer_price:{offer_id}")]]
        )

    p = (photo_url or "").strip()
    if not p:
        await bot.send_message(
            chat_id,
            card_text + "\n\n<i>Фото объявления не найдено в БД.</i>",
            parse_mode="HTML",
            reply_markup=price_kb,
            reply_to_message_id=reply_to,
        )
    else:
        try:
            await bot.send_photo(
                chat_id=chat_id,
                photo=p,
                caption=card_text,
                parse_mode="HTML",
                reply_markup=price_kb,
                reply_to_message_id=reply_to,
            )
        except Exception:
            await bot.send_message(
                chat_id,
                card_text + "\n\n<i>Не удалось отправить фото объявления.</i>",
                parse_mode="HTML",
                reply_markup=price_kb,
                reply_to_message_id=reply_to,
            )

    if reply_to:
        try:
            await _try_pin(bot, chat_id, reply_to)
        except Exception:
            pass


async def _send_generated_link_card(
    *,
    callback: CallbackQuery,
    offer_title: str | None,
    offer_price: str | None,
    photo_url: str | None,
    profile_display: str | None,
    service_code: str,
    link: str,
    offer_id: int | None = None,
    anchor_message_id: int | None = None,
    account_email: str | None = None,
    contact_email: str | None = None,
    inbox_label: str | None = None,
):
    await _send_generated_link_card_to_chat(
        callback.bot,
        int(callback.message.chat.id),
        offer_title=offer_title,
        offer_price=offer_price,
        photo_url=photo_url,
        profile_display=profile_display,
        service_code=service_code,
        link=link,
        offer_id=offer_id,
        anchor_message_id=anchor_message_id,
        account_email=account_email,
        contact_email=contact_email,
        inbox_label=inbox_label,
    )


def _norm_subject_for_match(subject: str) -> str:
    """Normalize email subject for offer matching.

    Keep behavior predictable:
    - strip common reply/forward prefixes (re/aw/fw/fwd)
    - trim
    """
    s = (subject or "").strip()
    if not s:
        return ""
    return re.sub(r"^(re|aw|fw|fwd)\s*:\s*", "", s, flags=re.I).strip()


async def _offer_link_by_subject_or_name(
    session,
    *,
    user_id: int,
    subject: str,
    from_name: str,
) -> str | None:
    """Fallback: try to resolve Offer.link by subject/title or seller name.

    This is the same idea as in cb_create_goo_link (in-memory flow),
    but used for the DB-bound flow too.
    """
    if not user_id:
        return None

    subj = _norm_subject_for_match(subject)
    fn = (from_name or "").strip()

    # 1) by title-ish subject
    if subj:
        row_t = (
            await session.execute(
                sa_select(Offer.link)
                .where(Offer.user_id == int(user_id))
                .where(func.lower(Offer.title).like(f"%{subj.lower()}%"))
                .where(Offer.link.is_not(None))
                .order_by(Offer.id.desc())
                .limit(1)
            )
        ).first()
        if row_t and row_t[0]:
            return str(row_t[0]).strip()

        # Some subjects include extra words like "Verkaufe".
        # If the subject is long, also try a smaller token window.
        try:
            parts = [p for p in re.split(r"\s+", subj) if p]
            if len(parts) >= 4:
                tail = " ".join(parts[-4:]).strip()
                if tail and tail.lower() != subj.lower():
                    row_t2 = (
                        await session.execute(
                            sa_select(Offer.link)
                            .where(Offer.user_id == int(user_id))
                            .where(func.lower(Offer.title).like(f"%{tail.lower()}%"))
                            .where(Offer.link.is_not(None))
                            .order_by(Offer.id.desc())
                            .limit(1)
                        )
                    ).first()
                    if row_t2 and row_t2[0]:
                        return str(row_t2[0]).strip()
        except Exception:
            pass

    # 2) by seller name
    if fn:
        row_n = (
            await session.execute(
                sa_select(Offer.link)
                .where(Offer.user_id == int(user_id))
                .where(func.lower(Offer.person_name).like(f"%{fn.lower()}%"))
                .where(Offer.link.is_not(None))
                .order_by(Offer.id.desc())
                .limit(1)
            )
        ).first()
        if row_n and row_n[0]:
            return str(row_n[0]).strip()

    return None


async def _get_acc_owner_user_id(session, acc_id: int) -> int | None:
    acc = (
        await session.execute(
            sa_select(EmailAccount).where(EmailAccount.id == int(acc_id))
        )
    ).scalars().first()
    return int(acc.user_id) if acc else None


async def _get_convlink(
    session,
    *,
    user_id: int,
    inbox_email: str,
    contact_email: str,
) -> ConversationLink | None:
    """
    Связка диалога для конкретного ящика и контакта.

    В МОДЕЛИ ConversationLink поля:
      - account_email — наш почтовый ящик (куда пришло письмо)
      - from_email    — email отправителя (продавца)

    Здесь:
      inbox_email   -> пишем/сравниваем с account_email
      contact_email -> пишем/сравниваем с from_email
    """
    inbox_keys = _email_keys(inbox_email)
    contact_keys = _email_keys(contact_email)
    if not inbox_keys or not contact_keys:
        return None

    return (
        await session.execute(
            sa_select(ConversationLink)
            .where(ConversationLink.user_id == int(user_id))
            .where(func.lower(ConversationLink.account_email).in_(inbox_keys))
            .where(func.lower(ConversationLink.from_email).in_(contact_keys))
            .order_by(ConversationLink.id.desc())
            .limit(1)
        )
    ).scalars().first()


async def _upsert_convlink(
    session,
    *,
    user_id: int,
    inbox_email: str,
    contact_email: str,
    ad_url: str | None = None,
    generated_link: str | None = None,
    generated_price: str | None = None,
    pinned_offer_id: int | None = None,
) -> None:
    """
    Обновить/создать запись ConversationLink.

    В МОДЕЛИ ConversationLink поля:
      - account_email — наш почтовый ящик (куда пришло письмо)
      - from_email    — email отправителя (продавца)
    """
    inbox = _canon_email(inbox_email)
    contact = _canon_email(contact_email)
    if not inbox or not contact:
        return

    conv = await _get_convlink(
        session,
        user_id=user_id,
        inbox_email=inbox,
        contact_email=contact,
    )
    if not conv:
        conv = ConversationLink(
            user_id=int(user_id),
            account_email=inbox,
            from_email=contact,
            ad_url=(ad_url or "").strip() or None,
            generated_link=(generated_link or "").strip() or None,
            last_generated_price=(generated_price or "").strip()[:64] or None,
            pinned_offer_id=int(pinned_offer_id) if pinned_offer_id else None,
        )
        session.add(conv)
    else:
        if ad_url:
            conv.ad_url = (ad_url or "").strip() or conv.ad_url
        if generated_link:
            conv.generated_link = (generated_link or "").strip() or conv.generated_link
        if generated_price:
            conv.last_generated_price = (generated_price or "").strip()[:64] or conv.last_generated_price
        if pinned_offer_id:
            conv.pinned_offer_id = int(pinned_offer_id)


async def _pin_generated_link_on_dialog_mails(
    session,
    *,
    user_id: int,
    inbox_email: str,
    contact_email: str,
    generated_link: str,
    generated_price: str | None = None,
    offer_id: int | None = None,
) -> None:
    """Все письма диалога получают последнюю ссылку/цену для HTML."""
    contact_keys = _email_keys(contact_email)
    _ = inbox_email
    link = (generated_link or "").strip()
    if not link:
        return
    values: dict = {"generated_link": link}
    price = (generated_price or "").strip()[:64]
    if price:
        values["offer_price"] = price
    if contact_keys:
        await session.execute(
            sa_update(IncomingMail)
            .where(IncomingMail.user_id == int(user_id))
            .where(func.lower(IncomingMail.from_email).in_(contact_keys))
            .values(**values)
        )
    if offer_id:
        await session.execute(
            sa_update(IncomingMail)
            .where(IncomingMail.user_id == int(user_id))
            .where(IncomingMail.resolved_offer_id == int(offer_id))
            .values(**values)
        )


async def _offer_link_by_sender_email(session, user_id: int, from_email: str) -> str | None:
    """Попробовать найти Offer.link по email отправителя.

    Правила:
    - single-name НЕ обрабатываем (нужен first.last)
    - сначала exact match OfferEmail.email == from_email
    - если нет, то first.last@gmail.com -> ищем OfferEmail.email LIKE 'first.last@%'
    """
    if not user_id or not from_email or "@" not in from_email:
        return None

    fe = from_email.strip().lower()
    local, domain = fe.split("@", 1)
    local = local.strip()
    domain = domain.strip().lower()

    # 1) exact
    row = (
        await session.execute(
            sa_select(Offer.link)
            .select_from(OfferEmail)
            .join(Offer, Offer.id == OfferEmail.offer_id)
            .where(Offer.user_id == int(user_id))
            .where(func.lower(OfferEmail.email) == fe)
            .where(Offer.link.is_not(None))
            .order_by(Offer.id.desc())
            .limit(1)
        )
    ).first()
    if row and row[0]:
        return str(row[0]).strip()

    # 1.5) Gmail: точки в local-part могут "исчезать" (gmail игнорирует '.')
    # пример: sorik.hajoyan@gmail.com -> sorikhajoyan@gmail.com
    if domain in ("gmail.com", "googlemail.com"):
        fe_nodot = fe.replace(".", "")
        row_g = (
            await session.execute(
                sa_select(Offer.link)
                .select_from(OfferEmail)
                .join(Offer, Offer.id == OfferEmail.offer_id)
                .where(Offer.user_id == int(user_id))
                # убираем точки у email в БД и у входящего email
                .where(func.replace(func.lower(OfferEmail.email), ".", "") == fe_nodot)
                .where(Offer.link.is_not(None))
                .order_by(Offer.id.desc())
                .limit(1)
            )
        ).first()
        if row_g and row_g[0]:
            return str(row_g[0]).strip()

    # 2) local-part match (first.last@domain -> first.last@ANY)
    # Для single-name у не-gmail почти всегда бесполезно, но тут не режем жестко,
    # чтобы не ломать нестандартные кейсы (и для gmail тоже).
    row2 = (
        await session.execute(
            sa_select(Offer.link)
            .select_from(OfferEmail)
            .join(Offer, Offer.id == OfferEmail.offer_id)
            .where(Offer.user_id == int(user_id))
            .where(func.lower(OfferEmail.email).like(local + "@%"))
            .where(Offer.link.is_not(None))
            .order_by(Offer.id.desc())
            .limit(1)
        )
    ).first()
    if row2 and row2[0]:
        return str(row2[0]).strip()

    # 3) python-side canonical fallback (handles gmail dots/+ and domain mismatches)
    try:
        fe_can = _canon_email(from_email)
        rows = (
            await session.execute(
                sa_select(OfferEmail.email, Offer.link)
                .select_from(OfferEmail)
                .join(Offer, Offer.id == OfferEmail.offer_id)
                .where(Offer.user_id == int(user_id))
                .where(Offer.link.is_not(None))
                .order_by(Offer.id.desc())
                .limit(800)
            )
        ).all()
        for em, lk in rows:
            if not lk:
                continue
            if _canon_email(em or "") == fe_can:
                return str(lk).strip()
    except Exception:
        pass

    return None


async def _offer_by_sender_email(session, user_id: int, from_email: str) -> tuple[Offer | None, int]:
    """Находит Offer по email отправителя.

    Для Gmail/Googlemail сравнение делается без точек в адресе,
    т.к. в реальности отправитель может ответить с варианта без точек.
    """
    fe = (from_email or "").strip().lower()
    if "@" not in fe:
        return None, 0

    domain = fe.split("@", 1)[1].strip().lower()
    if domain in ("gmail.com", "googlemail.com"):
        fe_nd = fe.replace(".", "")
        row = (
            await session.execute(
                select(Offer, func.count(OfferEmail.id))
                .join(OfferEmail, OfferEmail.offer_id == Offer.id)
                .where(Offer.user_id == user_id)
                .where(func.replace(func.lower(OfferEmail.email), ".", "") == fe_nd)
                .group_by(Offer.id)
                .limit(1)
            )
        ).first()
        if row:
            return row[0], int(row[1] or 0)
        return None, 0

    # обычный случай: точное совпадение
    row = (
        await session.execute(
            select(Offer, func.count(OfferEmail.id))
            .join(OfferEmail, OfferEmail.offer_id == Offer.id)
            .where(Offer.user_id == user_id)
            .where(func.lower(OfferEmail.email) == fe)
            .group_by(Offer.id)
            .limit(1)
        )
    ).first()
    if row:
        return row[0], int(row[1] or 0)
    return None, 0


def _extract_translation_from_card(text: str) -> str | None:
    try:
        m = re.search(
            r"(?is)<b>Перевод:</b>\s*<blockquote><code>(.*?)</code></blockquote>",
            text or "",
        )
        if m:
            return html.unescape(m.group(1)).strip()
    except Exception:
        pass
    return None


def _parse_acc_uid_callback(data: str, prefix: str) -> tuple[int, str] | None:
    try:
        parts = (data or "").split(":")
        if len(parts) < 3 or parts[0] != prefix:
            return None
        return int(parts[1]), ":".join(parts[2:])
    except Exception:
        return None


async def _run_mail_translate(callback: CallbackQuery, mail_id: int) -> None:
    async with Session() as session:
        mail = (
            await session.execute(
                sa_select(IncomingMail).where(IncomingMail.id == int(mail_id)).limit(1)
            )
        ).scalars().first()
        if not mail:
            return await callback.answer("Письмо не найдено в БД.", show_alert=True)

        body_full = (getattr(mail, "body", None) or "").strip()
        if not body_full:
            body_full = full_body_get(int(mail.account_id), str(mail.imap_uid))
        if not body_full:
            return await callback.answer("Нет текста для перевода.", show_alert=True)

        from services.incoming_mail_worker import _clean_mail_body_for_card

        shown = _clean_mail_body_for_card(body_full)
        shown = _strip_html(shown)
        if not shown:
            return await callback.answer("Нет текста для перевода.", show_alert=True)

    uid = callback.from_user.id
    if bg_is_running(uid, "translate"):
        return await callback.answer(toast("wait", "Перевод уже выполняется…"), show_alert=True)
    await callback.answer("Перевожу…", show_alert=False)

    mail_id_copy = int(mail_id)
    msg = callback.message
    bot = callback.bot

    async def _translate_job() -> None:
        translated = await translate_to_ru(shown, preserve_blocks=True)
        if not translated:
            try:
                await bot.send_message(
                    msg.chat.id,
                    f"{html_emoji('fail')} Не удалось перевести. Попробуйте позже.",
                    reply_to_message_id=msg.message_id,
                )
            except Exception:
                pass
            return
        async with Session() as session2:
            mail2 = (
                await session2.execute(
                    sa_select(IncomingMail).where(IncomingMail.id == mail_id_copy).limit(1)
                )
            ).scalars().first()
            if not mail2:
                return
            new_text, new_kb = await build_mail_card_from_mail(
                session2,
                mail2,
                translation=translated,
            )
        try:
            await msg.edit_text(
                new_text,
                reply_markup=new_kb,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
        except Exception:
            await bot.send_message(
                msg.chat.id,
                new_text,
                reply_markup=new_kb,
                parse_mode="HTML",
                reply_to_message_id=msg.message_id,
            )

    if not bg_start(uid, "translate", _translate_job()):
        return await callback.answer(toast("wait", "Перевод уже выполняется…"), show_alert=True)


@router.callback_query(F.data.startswith("mail_translate:"))
async def cb_mail_translate(callback: CallbackQuery) -> None:
    try:
        _, mail_id_s = (callback.data or "").split(":", 1)
        mail_id = int(mail_id_s)
    except Exception:
        return await callback.answer("Неверные данные", show_alert=True)
    return await _run_mail_translate(callback, mail_id)


@router.callback_query(F.data.startswith("mail_translate_stub:"))
async def cb_mail_translate_stub(callback: CallbackQuery) -> None:
    parsed = _parse_acc_uid_callback(callback.data or "", "mail_translate_stub")
    if not parsed:
        return await callback.answer("Неверные данные", show_alert=True)
    acc_id, uid = parsed
    card_mid = int(callback.message.message_id) if callback.message else None

    async with Session() as session:
        mail = await _load_incoming_mail_for_callback(
            session,
            acc_id=acc_id,
            uid=uid,
            tg_message_id=card_mid,
        )
    if mail:
        return await _run_mail_translate(callback, int(mail.id))

    body = full_body_get(acc_id, uid)
    if body:
        return await callback.answer(
            "Письмо сохраняется в базу. Нажмите «Перевести» через 5–10 сек.",
            show_alert=True,
        )
    return await callback.answer(
        "Письмо не найдено в базе. Подождите новое входящее или redeploy с последним коммитом.",
        show_alert=True,
    )


@router.callback_query(F.data.startswith("mail_view:"))
async def cb_mail_view_legacy(callback: CallbackQuery) -> None:
    """Старые кнопки «Развернуть» — обновляем карточку на формат со стрелкой в тексте."""
    try:
        _, mail_id_s, _mode = (callback.data or "").split(":", 2)
        mail_id = int(mail_id_s)
    except Exception:
        return await callback.answer("Неверные данные", show_alert=True)

    async with Session() as session:
        mail = (
            await session.execute(
                sa_select(IncomingMail).where(IncomingMail.id == int(mail_id)).limit(1)
            )
        ).scalars().first()
        if not mail:
            return await callback.answer("Письмо не найдено.", show_alert=True)
        cur = (callback.message.html_text or callback.message.text or "").strip()
        translation = _extract_translation_from_card(cur)
        new_text, new_kb = await build_mail_card_from_mail(session, mail, translation=translation)

    try:
        await callback.message.edit_text(
            new_text,
            reply_markup=new_kb,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
    except Exception:
        pass
    await callback.answer()


@router.callback_query(F.data.startswith("goo_mail:"))
async def cb_create_goo_link_from_db(callback: CallbackQuery):
    """Create AQUA link for incoming mail stored in DB."""

    try:
        _, mail_id = (callback.data or "").split(":", 1)
        mail_id = int(mail_id)
    except Exception:
        return await callback.answer("Неверные данные", show_alert=True)

    return await _enqueue_aqua_link_by_mail_id(callback, mail_id)


async def _create_aqua_link_from_db_work(callback: CallbackQuery, mail_id: int) -> None:
    async with Session() as session:
        try:
            await _create_aqua_link_from_db_work_impl(session, callback, mail_id)
        except Exception as e:
            logger.exception("create aqua link from db mail_id=%s", mail_id)
            try:
                await session.rollback()
            except Exception:
                pass
            if is_expired_callback_error(e):
                logger.warning("create aqua link: stale callback mail_id=%s", mail_id)
                return
            await callback.message.answer(
                f"{html_emoji('fail')} <b>Ошибка создания ссылки</b>\n<code>{_e(_aqua_link_user_error(e))}</code>",
                parse_mode="HTML",
            )
            await callback_answer_safe(callback)


async def _create_aqua_link_from_db_work_impl(
    session,
    callback: CallbackQuery,
    mail_id: int,
) -> None:
        # Ensure the telegram user is the owner in our DB
        tg_user = await get_or_create_user(session, int(callback.from_user.id))

        mail = (
            await session.execute(
                sa_select(IncomingMail).where(IncomingMail.id == int(mail_id)).limit(1)
            )
        ).scalars().first()

        if not mail:
            await callback.message.answer(f"{html_emoji('fail')} Письмо не найдено в БД")
            return await callback_answer_safe(callback, "Письмо не найдено в БД", show_alert=True)

        if int(mail.user_id) != int(tg_user.id):
            await callback.message.answer(f"{html_emoji('fail')} Нет доступа к этому письму")
            return await callback_answer_safe(callback, "Нет доступа к этому письму", show_alert=True)

        acc_id = int(mail.account_id)
        inbox_email = _canon_email(mail.account_email or "")
        contact_email = _canon_email(mail.from_email or "")
        from services.offer_storage import live_user_offer, normalize_incoming_seller_email

        contact_email = normalize_incoming_seller_email(contact_email) or contact_email

        subj_mail = (getattr(mail, "subject", "") or "").strip()
        body_mail = (getattr(mail, "body", "") or "").strip()

        await _sync_incoming_mail_offer_with_card(
            session, mail, tg_message=callback.message
        )

        from services.incoming_lead_resolve import resolve_offer_for_incoming_lead
        from services.offer_storage import offer_effective_link

        offer, url, _how, snap = await resolve_offer_for_incoming_lead(
            session,
            user_id=int(tg_user.id),
            contact_email=contact_email,
            subject=subj_mail,
            from_name=(getattr(mail, "from_name", "") or "").strip(),
            body_text=body_mail,
            resolved_offer_id=getattr(mail, "resolved_offer_id", None),
            mail_ad_url=(getattr(mail, "ad_url", "") or "").strip() or None,
            inbox_email=inbox_email,
            mailing_bound=bool(getattr(mail, "mailing_bound", False)),
        )
        url = (url or "").strip() or (
            (offer_effective_link(offer) or "").strip() if offer else ""
        )
        if offer:
            live_off = await live_user_offer(
                session, user_id=int(tg_user.id), offer_id=int(offer.id)
            )
            if live_off:
                mail.resolved_offer_id = int(live_off.id)
                mail.mailing_bound = True
                if url:
                    mail.ad_url = url
                pt = (snap.get("product_title") or "").strip()
                if pt:
                    mail.product_title = pt[:500]
                pr = (snap.get("offer_price") or "").strip()
                if pr:
                    mail.offer_price = pr[:64]
                ph = (snap.get("photo_url") or "").strip()
                if ph:
                    mail.photo_url = ph[:2000]
                sl = (snap.get("service_label") or "").strip()
                if sl:
                    mail.service_label = sl[:64]
                await _flush_incoming_mail_bind(session, mail, user_id=int(tg_user.id))
            else:
                mail.resolved_offer_id = None

        if not offer:
            subj_hint = (subj_mail or "").strip() or (
                product_title_from_subject(subj_mail) if subject_is_informative(subj_mail) else ""
            )
            oid_hint = getattr(mail, "resolved_offer_id", None) or _offer_id_from_incoming_card_message(
                callback.message
            )
            extra = ""
            if oid_hint:
                live_hint = await live_user_offer(
                    session, user_id=int(tg_user.id), offer_id=int(oid_hint)
                )
                if live_hint:
                    extra = (
                        f"\n<b>Лот в письме:</b> <code>{int(oid_hint)}</code> — "
                        "проверьте валидацию email и снова «Создать ссылку»."
                    )
                else:
                    extra = (
                        f"\n<b>Лот на карточке:</b> <code>{int(oid_hint)}</code> уже нет в базе. "
                        "Загрузите JSON заново и провалидируйте email продавца."
                    )
            await callback.message.answer(
                f"{html_emoji('fail')} <b>Не нашёл объявление для этого письма</b>\n\n"
                f"<b>Тема:</b> <code>{_e(subj_hint or '—')}</code>\n"
                f"<b>От:</b> <code>{_e(contact_email) or '—'}</code>{extra}\n\n"
                "Загрузите JSON с этим лотом, провалидируйте email продавца, затем снова «Создать ссылку».",
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
            await callback_answer_safe(callback)
            return

        url = (url or (offer_effective_link(offer) or "").strip() or (getattr(mail, "ad_url", "") or "").strip())
        if not url:
            subj_hint = product_title_from_subject(subj_mail) if subject_is_informative(subj_mail) else subj_mail
            await callback.message.answer(
                f"{html_emoji('fail')} <b>Нет item_link в БД для лота</b> <code>{int(offer.id)}</code>\n\n"
                f"<b>Тема:</b> <code>{_e(subj_hint or '—')}</code>\n"
                f"<b>От:</b> <code>{_e(contact_email) or '—'}</code>\n\n"
                "Перезагрузите JSON с item_link или провалидируйте email заново.",
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
            await callback_answer_safe(callback)
            return

        if offer:
            live_keep = await live_user_offer(
                session, user_id=int(tg_user.id), offer_id=int(offer.id)
            )
            if live_keep:
                mail.resolved_offer_id = int(live_keep.id)
                mail.mailing_bound = True
            else:
                mail.resolved_offer_id = None
                mail.mailing_bound = False
        offer, url, title, price, offer_image = await finalize_aqua_listing_context(
            session,
            user_id=int(tg_user.id),
            listing_url=url,
            offer=offer,
            subject=subj_mail,
        )
        offer_id = int(offer.id) if offer else None
        offer_title = title

        if not title:
            await callback.message.answer(f"{html_emoji('fail')} Нет названия в теме письма (Re: …).")
            await callback_answer_safe(callback)
            return

        try:
            aqua_url = await _aqua_generate_link(
                session,
                tg_user,
                title=title,
                price=price,
                listing_url=url,
                image=offer_image,
            )
        except AquaError as e:
            await callback.message.answer(f"{html_emoji('fail')} <b>API генерации</b>\n<code>{_e(str(e)[:400])}</code>", parse_mode="HTML")
            await callback_answer_safe(callback)
            return

        await _upsert_convlink(
            session,
            user_id=int(tg_user.id),
            inbox_email=inbox_email,
            contact_email=contact_email,
            ad_url=url,
            generated_link=aqua_url,
            generated_price=str(price) if price else None,
            pinned_offer_id=offer_id,
        )
        await _pin_generated_link_on_dialog_mails(
            session,
            user_id=int(tg_user.id),
            inbox_email=inbox_email,
            contact_email=contact_email,
            generated_link=aqua_url,
            generated_price=str(price) if price else None,
            offer_id=offer_id,
        )
        mail.generated_link = aqua_url
        if offer_id:
            live_final = await live_user_offer(
                session, user_id=int(tg_user.id), offer_id=int(offer_id)
            )
            if live_final:
                mail.resolved_offer_id = int(live_final.id)
                from services.offer_storage import set_offer_aqua_pin

                set_offer_aqua_pin(live_final, link=aqua_url, price=str(price) if price else None)
            else:
                mail.resolved_offer_id = None
                offer_id = None
        mail.ad_url = url
        if title:
            mail.product_title = title[:500]
        if price:
            mail.offer_price = str(price)[:64]
        if offer_image:
            mail.photo_url = str(offer_image)[:2000]
        await _flush_incoming_mail_bind(session, mail, user_id=int(tg_user.id))
        await session.commit()

        mail_uid = str(getattr(mail, "imap_uid", "") or "")
        acc_id_fm = int(mail.account_id)
        meta_fm = FULL_META.get((acc_id_fm, mail_uid)) or {}
        anchor = _resolve_mail_anchor(acc_id_fm, mail_uid, meta_fm, callback.message)
        inbox_label = (getattr(tg_user, "sender_name", None) or "").strip()
        service = await get_user_aqua_service(session, tg_user)
        prof_display = (
            await get_user_aqua_profile_display(session, tg_user) or ""
        ).strip() or "—"
        from services.api_teams import get_selected_team_config

        team_cfg = await get_selected_team_config(session, tg_user)
        display_service = _generate_card_service_label(
            team_id=team_cfg.team_id,
            service_code=team_cfg.service_code or service,
            offer=offer,
        )

        await _send_generated_link_card(
            callback=callback,
            offer_title=offer_title or title,
            offer_price=price,
            photo_url=offer_image,
            profile_display=prof_display,
            service_code=display_service,
            link=aqua_url,
            offer_id=offer_id,
            anchor_message_id=anchor,
            account_email=inbox_email,
            contact_email=contact_email,
            inbox_label=inbox_label or None,
        )


async def _enqueue_aqua_link_by_mail_id(
    callback: CallbackQuery, mail_id: int, *, ack: bool = True
) -> None:
    uid_tg = callback.from_user.id
    bg_key = f"aqua_link:{int(mail_id)}"
    if bg_is_running(uid_tg, bg_key):
        return await callback_answer_safe(
            callback, toast("wait", "Ссылка уже создаётся…"), show_alert=True
        )
    if ack:
        await callback_answer_safe(callback, toast("wait", "Создаю ссылку…"))

    async def _link_job() -> None:
        await _run_aqua_link_bg(callback, lambda: _create_aqua_link_from_db_work(callback, int(mail_id)))

    if not bg_start(uid_tg, bg_key, _link_job()):
        return await callback_answer_safe(
            callback, toast("wait", "Ссылка уже создаётся…"), show_alert=True
        )


@router.callback_query(F.data.startswith("goo_link:"))
async def cb_create_goo_link(callback: CallbackQuery):
    parsed = _parse_acc_uid_callback(callback.data or "", "goo_link")
    if not parsed:
        return await callback_answer_safe(callback, "Неверные данные", show_alert=True)
    acc_id, uid = parsed
    card_mid = int(callback.message.message_id) if callback.message else None

    await callback_answer_safe(callback, toast("wait", "Создаю ссылку…"))

    async with Session() as session:
        mail = await _load_incoming_mail_for_callback(
            session,
            acc_id=acc_id,
            uid=uid,
            tg_message_id=card_mid,
        )
    if mail:
        return await _enqueue_aqua_link_by_mail_id(callback, int(mail.id), ack=False)

    from handlers.mail_templates import _load_meta_from_db, _STALE_MAIL_MSG

    meta = full_meta_get(acc_id, uid) or await _load_meta_from_db(acc_id, uid)
    if not meta:
        await callback.message.answer(
            "Письмо ещё не в базе. Подождите 5–10 сек и нажмите снова, "
            "или дождитесь следующего входящего.",
        )
        return

    uid_tg = callback.from_user.id
    if bg_is_running(uid_tg, "aqua_link"):
        return

    async def _link_job() -> None:
        await _run_aqua_link_bg(
            callback, lambda: _create_aqua_link_work(callback, acc_id, uid, meta)
        )

    bg_start(uid_tg, "aqua_link", _link_job())


async def _create_aqua_link_work(callback: CallbackQuery, acc_id: int, uid: str, meta: dict) -> None:
    inbox_email = _canon_email((meta.get("account_email") or ""))
    contact_email = _canon_email((meta.get("from_email") or ""))
    from services.offer_storage import normalize_incoming_seller_email

    contact_email = normalize_incoming_seller_email(contact_email) or contact_email

    async with Session() as session:
        owner_user_id = await _get_acc_owner_user_id(session, acc_id)
        if not owner_user_id:
            await callback.message.answer(f"{html_emoji('fail')} Аккаунт не найден в БД")
            return await callback_answer_safe(callback, "Аккаунт не найден в БД", show_alert=True)

        mail_pre = (
            await session.execute(
                sa_select(IncomingMail)
                .where(IncomingMail.account_id == int(acc_id))
                .where(IncomingMail.imap_uid == int(uid))
                .where(IncomingMail.user_id == int(owner_user_id))
                .limit(1)
            )
        ).scalars().first()

        subj_pre = (getattr(mail_pre, "subject", "") or meta.get("subject") or "").strip()
        body_pre = (getattr(mail_pre, "body", "") or "").strip() if mail_pre else ""

        offer = None
        url = ""
        if mail_pre:
            offer, url = await _resolve_and_bind_incoming_mail_offer(
                session,
                mail=mail_pre,
                inbox_email=inbox_email,
            )
        resolved_id = int(offer.id) if offer else (
            getattr(mail_pre, "resolved_offer_id", None) if mail_pre else None
        )
        mailing_bound = bool(getattr(mail_pre, "mailing_bound", False)) if mail_pre else False

        if not url:
            resolved_id, mailing_bound = await _aqua_resolve_pins_for_mail(
                session,
                user_id=int(owner_user_id),
                subject=subj_pre,
                resolved_offer_id=resolved_id,
                mailing_bound=mailing_bound,
                inbox_email=inbox_email,
                contact_email=contact_email,
            )
            offer, url = await resolve_offer_for_aqua_link(
                session,
                user_id=int(owner_user_id),
                from_email=contact_email,
                subject=subj_pre,
                from_name=(getattr(mail_pre, "from_name", "") or meta.get("from_name") or "").strip(),
                body_text=body_pre,
                resolved_offer_id=resolved_id,
                mail_ad_url=(getattr(mail_pre, "ad_url", "") or "").strip() if mail_pre else None,
                inbox_email=inbox_email,
                mailing_bound=mailing_bound,
            )

        if not url:
            from services.offer_matching import _load_offer
            from services.offer_storage import offer_effective_link

            fallback_oid = None
            if mail_pre and getattr(mail_pre, "resolved_offer_id", None):
                fallback_oid = int(mail_pre.resolved_offer_id)
            elif resolved_id:
                fallback_oid = int(resolved_id)
            if fallback_oid:
                off_fb = await _load_offer(
                    session, user_id=int(owner_user_id), offer_id=fallback_oid
                )
                url_fb = (offer_effective_link(off_fb) or "").strip() if off_fb else ""
                if not url_fb and mail_pre:
                    url_fb = (getattr(mail_pre, "ad_url", "") or "").strip()
                if url_fb:
                    offer = off_fb
                    url = url_fb

        if not url:
            offer_lc, url_lc = await _aqua_last_chance_offer_url(
                session,
                user_id=int(owner_user_id),
                mail=mail_pre,
                inbox_email=inbox_email,
                contact_email=contact_email,
                resolved_id=int(resolved_id) if resolved_id else None,
                subject=subj_pre,
                body_text=(getattr(mail_pre, "body", "") or "") if mail_pre else "",
            )
            if url_lc:
                offer = offer_lc or offer
                url = url_lc

        if not url:
            subj_hint = (subj_pre or "").strip() or (
                product_title_from_subject(subj_pre) if subject_is_informative(subj_pre) else ""
            )
            await callback.message.answer(
                f"{html_emoji('fail')} <b>Не нашёл объявление для этого письма</b>\n\n"
                f"<b>Тема:</b> <code>{_e(subj_hint or '—')}</code>\n"
                f"<b>От:</b> <code>{_e(contact_email) or '—'}</code>\n\n"
                "Загрузите JSON с этим лотом и провалидируйте email (<code>item_link</code>).",
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
            return await callback_answer_safe(callback)

        user = await get_or_create_user(session, int(callback.from_user.id))

        mail = mail_pre
        if mail and offer:
            mail.resolved_offer_id = int(offer.id)

        offer, url, title, price, offer_image = await finalize_aqua_listing_context(
            session,
            user_id=int(owner_user_id),
            listing_url=url,
            offer=offer,
            subject=subj_pre,
        )
        offer_id = int(offer.id) if offer else None
        offer_title = title

        if not title:
            await callback.message.answer(f"{html_emoji('fail')} Нет названия в теме письма (Re: …).")
            return await callback_answer_safe(callback)

        service = await get_user_aqua_service(session, user)
        prof_display = (
            await get_user_aqua_profile_display(session, user) or ""
        ).strip() or "—"
        from services.api_teams import get_selected_team_config

        team_cfg = await get_selected_team_config(session, user)
        display_service = _generate_card_service_label(
            team_id=team_cfg.team_id,
            service_code=team_cfg.service_code or service,
            offer=offer,
        )

        try:
            aqua_url = await _aqua_generate_link(
                session,
                user,
                title=title,
                price=price,
                listing_url=url,
                image=offer_image,
            )
        except AquaError as e:
            await callback.message.answer(
                f"{html_emoji('fail')} <b>API генерации</b>\n<code>{_e(str(e)[:400])}</code>",
                parse_mode="HTML",
            )
            return await callback_answer_safe(callback)

        await _upsert_convlink(
            session,
            user_id=int(owner_user_id),
            inbox_email=inbox_email,
            contact_email=contact_email,
            ad_url=url,
            generated_link=aqua_url,
            generated_price=str(price) if price else None,
            pinned_offer_id=offer_id,
        )
        await _pin_generated_link_on_dialog_mails(
            session,
            user_id=int(owner_user_id),
            inbox_email=inbox_email,
            contact_email=contact_email,
            generated_link=aqua_url,
            generated_price=str(price) if price else None,
            offer_id=offer_id,
        )
        if mail:
            mail.generated_link = aqua_url
            if offer_id:
                mail.resolved_offer_id = int(offer_id)
                from services.offer_storage import set_offer_aqua_pin

                set_offer_aqua_pin(offer, link=aqua_url, price=str(price) if price else None)
            mail.ad_url = url
        await session.commit()

        inbox_label = (getattr(user, "sender_name", None) or "").strip()
        anchor = _resolve_mail_anchor(acc_id, uid, meta, callback.message)

        await _send_generated_link_card(
            callback=callback,
            offer_title=offer_title or title,
            offer_price=price,
            photo_url=offer_image,
            profile_display=prof_display,
            service_code=display_service,
            link=aqua_url,
            offer_id=offer_id,
            anchor_message_id=anchor,
            account_email=inbox_email,
            contact_email=contact_email,
            inbox_label=inbox_label or None,
        )


@router.callback_query(F.data.startswith("mail_reply_db:"))
async def cb_mail_reply_db(callback: CallbackQuery, state: FSMContext):
    try:
        mail_id = int((callback.data or "").split(":", 1)[1])
    except Exception:
        return await callback.answer("Неверные данные", show_alert=True)

    async with Session() as session:
        mail = (
            await session.execute(
                sa_select(IncomingMail).where(IncomingMail.id == int(mail_id)).limit(1)
            )
        ).scalars().first()
    if not mail:
        return await callback.answer("Письмо не найдено в БД", show_alert=True)

    await _open_mail_reply_menu(
        callback,
        state,
        acc_id=int(mail.account_id),
        uid=str(mail.imap_uid),
        mail_id=int(mail.id),
    )


@router.callback_query(F.data.func(_is_primary_mail_reply_cb))
async def cb_mail_reply(callback: CallbackQuery, state: FSMContext):
    try:
        _, acc_id, uid = (callback.data or "").split(":", 2)
        acc_id = int(acc_id)
    except Exception:
        return await callback.answer("Неверные данные", show_alert=True)

    await _open_mail_reply_menu(callback, state, acc_id=acc_id, uid=str(uid))


@router.callback_query(F.data.startswith("mail_reply_mode:"))
async def cb_mail_reply_mode(callback: CallbackQuery, state: FSMContext):
    """Choice menu after clicking "Написать ещё"."""
    try:
        _, mode, acc_id, uid = (callback.data or "").split(":", 3)
        acc_id = int(acc_id)
    except Exception:
        return await callback.answer("Неверные данные", show_alert=True)

    data = await state.get_data()

    if mode in {"cancel"}:
        ui_mid = data.get("ui_message_id")
        anchor_mid = data.get("anchor_message_id")
        if ui_mid and int(ui_mid) != int(anchor_mid or 0):
            await _delete_message_safe(
                callback.bot,
                callback.message.chat.id,
                int(ui_mid),
            )
        await state.clear()
        return await callback.answer("Отменено")

    if mode in {"back"}:
        await state.set_state(_MailReplyState.waiting_choice)
        try:
            await callback.message.edit_text(
                REPLY_CHOICE_TEXT,
                reply_markup=_kb_reply_choice(acc_id, uid),
            )
        except Exception:
            ui = await callback.message.answer(
                REPLY_CHOICE_TEXT,
                reply_markup=_kb_reply_choice(acc_id, uid),
            )
            await state.update_data(ui_message_id=int(ui.message_id))
        else:
            await state.update_data(ui_message_id=int(callback.message.message_id))
        return await callback.answer()

    # preset picker
    if mode == "preset":
        items = await load_templates(int(callback.from_user.id))
        if not items:
            return await callback.answer(f"Нет шаблонов. Добавь их в {html_emoji('burst')} Шаблоны", show_alert=True)

        preset_mail_id = data.get("mail_id")
        try:
            preset_mail_id = int(preset_mail_id) if preset_mail_id else None
        except (TypeError, ValueError):
            preset_mail_id = None
        pick_kb = _kb_preset_pick(items, acc_id, uid, mail_id=preset_mail_id)
        try:
            await callback.message.edit_text(
                f"{html_emoji('profile')} <b>Ваши шаблоны:</b>\n\nНажмите на пресет для отправки",
                parse_mode="HTML",
                reply_markup=pick_kb,
            )
        except Exception:
            ui = await callback.message.answer(
                f"{html_emoji('profile')} <b>Ваши шаблоны:</b>\n\nНажмите на пресет для отправки",
                parse_mode="HTML",
                reply_markup=pick_kb,
            )
            await state.update_data(ui_message_id=int(ui.message_id))
        else:
            await state.update_data(ui_message_id=int(callback.message.message_id))
        return await callback.answer()

    # html picker
    if mode == "html":
        async with Session() as session:
            to_email, subject, account_email = await _resolve_reply_recipient(
                session,
                acc_id,
                uid,
                meta=FULL_META.get((acc_id, uid)),
                state_data=data,
                mail_id=data.get("mail_id"),
            )
        await state.update_data(
            to_email=to_email,
            subject=subject,
            account_email=account_email,
        )
        html_text = (
            f"{html_emoji('puzzle')} <b>HTML</b>\n\n"
            f"Кому: <code>{_e(to_email) or '—'}</code>\n"
            f"От ящика: <code>{_e(account_email) or '—'}</code>\n\n"
            "Выберите шаблон:"
        )
        try:
            await callback.message.edit_text(
                html_text,
                parse_mode="HTML",
                reply_markup=_kb_html_pick(acc_id, uid),
            )
        except Exception:
            ui = await callback.message.answer(
                html_text,
                parse_mode="HTML",
                reply_markup=_kb_html_pick(acc_id, uid),
            )
            await state.update_data(ui_message_id=int(ui.message_id))
        else:
            await state.update_data(ui_message_id=int(callback.message.message_id))
        return await callback.answer()

    return await callback.answer("Ок")


@router.callback_query(F.data.startswith("mail_reply_preset:"))
async def cb_mail_reply_preset_send(callback: CallbackQuery, state: FSMContext):
    try:
        _, acc_id, mail_uid, tid = (callback.data or "").split(":", 3)
        acc_id = int(acc_id)
        tid = int(tid)
    except Exception:
        return await callback.answer("Неверные данные", show_alert=True)

    data = await state.get_data()
    async with Session() as session:
        to_email, subject, account_email = await _resolve_reply_recipient(
            session,
            acc_id,
            mail_uid,
            meta=FULL_META.get((acc_id, mail_uid)),
            state_data=data,
            mail_id=data.get("mail_id"),
        )
    if not to_email or "@" not in to_email:
        return await callback.answer(
            "Не вижу email получателя. Откройте карточку письма снова.",
            show_alert=True,
        )
    await state.update_data(
        to_email=to_email,
        subject=subject,
        account_email=account_email,
    )

    tg_id = int(callback.from_user.id)
    preset_body = ""

    db_user_id: int | None = None
    async with Session() as session:
        user = await get_or_create_user(session, tg_id)
        db_user_id = int(user.id)
        tmpl_pre = (
            await session.execute(
                sa_select(QuickTemplate)
                .where(QuickTemplate.user_id == int(user.id))
                .where(QuickTemplate.id == int(tid))
            )
        ).scalar_one_or_none()
        if tmpl_pre:
            preset_body = (tmpl_pre.body or "").strip()

    if not (preset_body or "").strip():
        return await callback.answer("Пресет пустой или не найден", show_alert=True)

    async def _send() -> tuple[bool, str | None, str | None]:
        async with Session() as session:
            user = await get_or_create_user(session, tg_id)
            acc = (
                await session.execute(sa_select(EmailAccount).where(EmailAccount.id == int(acc_id)))
            ).scalar_one_or_none()
            if not acc:
                return False, "SMTP аккаунт не найден", None
            out_subject = _reply_subject(subject)
            from services.html_reply import live_account_sender_display_name
            from services.incoming_mail_worker import FULL_BODIES

            meta_now = FULL_META.get((acc_id, mail_uid)) or {}
            parent_body = ""
            mail_mid = data.get("mail_id")
            try:
                mail_mid_i = int(mail_mid) if mail_mid else None
            except Exception:
                mail_mid_i = None
            m_body = None
            if mail_mid_i:
                m_body = await _load_incoming_mail_by_id(session, mail_mid_i)
            if m_body is None:
                m_body = await _load_incoming_mail_for_uid(session, int(acc_id), str(mail_uid))
            if m_body:
                parent_body = (m_body.body or "").strip()
                out_subject = _reply_subject(
                    (m_body.outgoing_mail_subject or "").strip()
                    or (m_body.subject or "").strip()
                    or subject
                )
            if not parent_body:
                parent_body = (FULL_BODIES.get((int(acc_id), str(mail_uid))) or "").strip()
            sender_name = await live_account_sender_display_name(session, user)
            body_copy = await compose_threaded_reply_body(
                session,
                user_id=int(user.id),
                to_email=to_email,
                inbox_email=getattr(acc, "email", None) or account_email or "",
                reply_text=preset_body,
                parent_from_name=meta_now.get("from_name"),
                parent_from_email=to_email,
                parent_date_str=meta_now.get("date_str"),
                parent_body=parent_body,
                sender_name=sender_name,
            )
            thread_kw = await _reply_thread_kwargs(
                session,
                acc_id=int(acc_id),
                uid=str(mail_uid),
                mail_id=mail_mid_i,
                meta=meta_now,
                mail_row=m_body,
                user_id=int(user.id),
                to_email=to_email,
                account_email=getattr(acc, "email", None) or account_email,
                smtp_password=getattr(acc, "password", None),
            )
            uid_db = int(user.id)
            inbox_em = getattr(acc, "email", None) or account_email or ""
            try:
                session.expunge(acc)
            except Exception:
                pass
        ok, err, msgid = await send_email_via_account_with_proxy(
            None,
            uid_db,
            acc,
            to_email,
            out_subject,
            body_copy,
            sender_name=sender_name,
            fast=True,
            **thread_kw,
        )
        if ok:
            await _remember_reply_msgid(
                user_id=uid_db,
                inbox_email=inbox_em,
                contact_email=to_email,
                msgid=msgid,
                references=thread_kw.get("references"),
            )
        return ok, err, msgid

    meta_fm = FULL_META.get((acc_id, mail_uid)) or {}
    state_snap = dict(data)

    async def _notify_builder() -> ReplyNotifyCtx | None:
        return await _reply_notify_build_async(
            acc_id=acc_id,
            uid=str(mail_uid),
            meta=meta_fm,
            state_data=state_snap,
            body_text=preset_body,
            is_preset=True,
            extra_cleanup=[callback.message.message_id],
            user_id=db_user_id,
        )

    await state.clear()
    if not await _bg_incoming_smtp(callback, tg_id, _send, notify_builder=_notify_builder):
        return


def _reply_subject(subject: str) -> str:
    # Не трогаем тире/юникод — иначе тема не совпадёт с оригиналом и Gmail
    # откроет второй диалог даже при верном In-Reply-To.
    s = re.sub(r"\s+", " ", (subject or "").replace("\r", " ").replace("\n", " ")).strip()
    prefix = re.compile(r"^(re|aw|fw|fwd|sv|antw)\s*:\s*", re.I)
    while True:
        nxt = prefix.sub("", s).strip()
        if nxt == s:
            break
        s = nxt
    return f"Re: {s}" if s else "Re:"


async def compose_threaded_reply_body(
    session,
    *,
    user_id: int,
    to_email: str,
    inbox_email: str,
    reply_text: str,
    parent_from_name: str | None = None,
    parent_from_email: str | None = None,
    parent_date_str: str | None = None,
    parent_body: str | None = None,
    sender_name: str | None = None,
) -> str:
    """Пресет + jaaa + тело /send, если его нет во входящем."""
    from services.email_threading import format_gmail_style_reply_body
    from services.mailing_send_log import load_last_mailing_quote

    root: dict = {}
    try:
        root = await load_last_mailing_quote(
            session,
            user_id=int(user_id),
            contact_email=to_email,
            inbox_email=inbox_email,
        )
    except Exception:
        root = {}
    return format_gmail_style_reply_body(
        reply_text,
        parent_from_name=parent_from_name,
        parent_from_email=parent_from_email,
        parent_date_str=parent_date_str,
        parent_body=parent_body,
        root_body=(root.get("body") or "").strip() or None,
        root_from_name=sender_name,
        root_from_email=(root.get("from_account_email") or inbox_email or "").strip() or None,
    )


async def _reply_thread_kwargs(
    session,
    *,
    acc_id: int,
    uid: str,
    mail_id: int | None = None,
    meta: dict | None = None,
    mail_row=None,
    user_id: int | None = None,
    to_email: str | None = None,
    account_email: str | None = None,
    smtp_password: str | None = None,
) -> dict:
    """In-Reply-To = оригинал рассылки; References = cold → jaaa."""
    import logging

    from services.email_threading import (
        build_references_header,
        load_dialog_thread_state,
        normalize_rfc_message_id,
        resolve_inbound_parent_references,
        resolve_inbound_rfc_message_id,
        resolve_outbound_rfc_message_id,
        threading_send_kwargs_for_dialog,
        usable_thread_message_id,
    )

    log = logging.getLogger(__name__)
    mid = int(mail_id) if mail_id else None
    if mid is None and mail_row is not None and getattr(mail_row, "id", None):
        try:
            mid = int(mail_row.id)
        except Exception:
            mid = None
    if mail_row is None and mid:
        mail_row = await _load_incoming_mail_by_id(session, mid)
    if mail_row is None and acc_id and uid:
        mail_row = await _load_incoming_mail_for_uid(session, acc_id, uid)
    if mail_row is not None:
        extra = _meta_from_incoming_mail(mail_row)
        meta = {**(meta or {}), **{k: v for k, v in extra.items() if v}}

    inbound = None
    if mail_row is not None:
        inbound = normalize_rfc_message_id(getattr(mail_row, "rfc_message_id", None))
    if not inbound:
        inbound = await resolve_inbound_rfc_message_id(
            session,
            acc_id=acc_id,
            uid=uid,
            mail_id=mid,
            meta=meta,
            from_email=to_email,
        )

    parent_refs = None
    if mail_row is not None:
        refs = (getattr(mail_row, "rfc_references", None) or "").strip()
        irt = normalize_rfc_message_id(getattr(mail_row, "rfc_in_reply_to", None))
        if refs or irt:
            parent_refs = build_references_header(*(refs.split() if refs else []), irt)
    if not parent_refs:
        parent_refs = await resolve_inbound_parent_references(
            session, mail_id=mid, meta=meta
        )

    contact = (to_email or "").strip()
    if not contact and meta:
        contact = str(meta.get("from_email") or "").strip()
    if not contact and mail_row is not None:
        contact = str(getattr(mail_row, "from_email", "") or "").strip()

    inbox = (account_email or "").strip()
    if not inbox and meta:
        inbox = str(meta.get("account_email") or "").strip()
    if not inbox and mail_row is not None:
        inbox = str(getattr(mail_row, "account_email", "") or "").strip()

    cold_outbound = None
    last_ours = None
    dialog_refs = None
    uid_user = int(user_id) if user_id else 0
    if not uid_user and mail_row is not None and getattr(mail_row, "user_id", None):
        uid_user = int(mail_row.user_id)
    if uid_user and contact:
        cold_outbound = await resolve_outbound_rfc_message_id(
            session,
            user_id=uid_user,
            contact_email=contact,
            inbox_email=inbox or None,
        )
        if inbox:
            last_ours, dialog_refs = await load_dialog_thread_state(
                session,
                user_id=uid_user,
                inbox_email=inbox,
                contact_email=contact,
            )
        # Корень = id рассылки, который видит получатель (не Sent @mail.gmail.com).
        from services.email_threading import prefer_thread_root_message_id

        log_cold = usable_thread_message_id(cold_outbound)
        seller_root = None
        if parent_refs:
            seller_root = usable_thread_message_id(
                (parent_refs or "").split()[0] if parent_refs else None
            )
        dialog_first = None
        if dialog_refs:
            dialog_first = usable_thread_message_id(
                (dialog_refs or "").split()[0] if dialog_refs else None
            )
        # Self-test: карточка = сама рассылка (нет In-Reply-To) → inbound MID из Inbox.
        inbound_is_cold = bool(inbound) and not (
            (getattr(mail_row, "rfc_in_reply_to", None) or "").strip()
            if mail_row is not None
            else (meta or {}).get("rfc_in_reply_to")
        )
        if inbound_is_cold:
            cold_outbound = prefer_thread_root_message_id(
                inbound,
                log_cold,
                seller_root,
                last_ours,
                dialog_first,
            )
        else:
            cold_outbound = prefer_thread_root_message_id(
                log_cold,
                seller_root,
                inbound,
                last_ours,
                dialog_first,
            )
        # Sent refresh только если корня нет; @mail.gmail.com отсекается внутри.
        if not usable_thread_message_id(cold_outbound) and (smtp_password or "").strip() and inbox:
            try:
                from services.email_threading import refresh_cold_message_id_from_sent

                got = await refresh_cold_message_id_from_sent(
                    session,
                    user_id=uid_user,
                    account_email=inbox,
                    account_password=smtp_password,
                    contact_email=contact,
                    subject=(
                        (getattr(mail_row, "outgoing_mail_subject", None) or "")
                        if mail_row is not None
                        else ""
                    )
                    or ((meta or {}).get("subject") if meta else "")
                    or "",
                )
                if got:
                    cold_outbound = got
            except Exception:
                log.exception("refresh cold Message-ID from Sent failed to=%s", (contact or "")[:80])

    kw = threading_send_kwargs_for_dialog(
        inbound_rfc_message_id=inbound,
        cold_outbound_rfc_message_id=cold_outbound,
        last_our_outbound_rfc_message_id=last_ours if last_ours != cold_outbound else None,
        parent_references=parent_refs,
        dialog_references=dialog_refs,
    )
    if not kw:
        log.warning(
            "reply threading empty acc=%s uid=%s mail_id=%s to=%s — Gmail may split thread",
            acc_id,
            uid,
            mid,
            (contact or "")[:80],
        )
    else:
        log.info(
            "reply threading acc=%s mail_id=%s in_reply_to=%s refs=%s",
            acc_id,
            mid,
            (kw.get("in_reply_to") or "")[:80],
            (kw.get("references") or "")[:160],
        )
    return kw


async def _remember_reply_msgid(
    *,
    user_id: int,
    inbox_email: str,
    contact_email: str,
    msgid: str | None,
    references: str | None = None,
    smtp_password: str | None = None,
    subject: str | None = None,
) -> None:
    if not msgid or not user_id:
        return
    try:
        from database import db_session
        from services.email_threading import remember_dialog_outbound

        store_mid = msgid
        # Не подменяем клиентский MID на Sent @mail.gmail.com — у получателя
        # в Inbox обычно остаётся тот id, что ушёл в SMTP DATA.
        from services.email_threading import is_client_smtp_message_id, normalize_rfc_message_id

        local_norm = normalize_rfc_message_id(msgid)
        if (
            smtp_password
            and inbox_email
            and local_norm
            and not is_client_smtp_message_id(local_norm)
        ):
            try:
                from services.smtp_delivery_verify import fetch_real_sent_message_id

                real_mid = await fetch_real_sent_message_id(
                    inbox_email,
                    smtp_password,
                    subject=subject or "",
                    to_email=contact_email,
                    local_message_id=msgid,
                    wait_sec=2.0,
                )
                if real_mid:
                    store_mid = real_mid
            except Exception:
                logger.exception(
                    "fetch real sent msgid failed user=%s to=%s",
                    user_id,
                    (contact_email or "")[:80],
                )

        async with db_session() as session:
            await remember_dialog_outbound(
                session,
                user_id=int(user_id),
                inbox_email=inbox_email,
                contact_email=contact_email,
                outbound_message_id=store_mid,
                references_header=references,
            )
            await session.commit()
    except Exception:
        logger.exception(
            "remember reply msgid failed user=%s to=%s",
            user_id,
            (contact_email or "")[:80],
        )


def _html_attachment_filename(subject: str) -> str:
    base = re.sub(r"[^\w\-]+", "_", (subject or "reply")[:60]).strip("_") or "reply"
    return f"{base}.html"


def _html_nick_key_for_service(service: str) -> str:
    service = (service or "").strip()
    return f"html_nick_{service}" if service else HTML_NICK_KEY


async def _offer_title_for_email(session: Session, user_id: int, to_email: str) -> str:
    try:
        canon = _canon_email(to_email)
        off = (
            await session.execute(
                sa_select(Offer)
                .join(OfferEmail, OfferEmail.offer_id == Offer.id)
                .where(Offer.user_id == int(user_id))
                .where(OfferEmail.email == canon)
                .order_by(Offer.id.desc())
                .limit(1)
            )
        ).scalars().first()
        if off:
            return (off.title or "").strip()
    except Exception:
        pass
    return ""


async def _load_html_template_for_user(session: Session, user: User, filename: str) -> tuple[str, str | None]:
    """HTML только из data/HTML/<сервис>/."""
    from services.html_templates import load_html_for_user

    html, _subdir, err = await load_html_for_user(
        session, user, aqua_service_key=AQUA_SERVICE_KEY, filename=filename
    )
    return html, err


def _apply_link(html_text: str, link: str) -> str:
    if not html_text:
        return ""
    if not link:
        return html_text
    from utils.re_literal import re_sub_literal

    return re_sub_literal(r"\{\{\s*LINK\s*\}\}", link, html_text, flags=re.I)


@router.callback_query(F.data.startswith("mail_reply_html:"))
async def cb_mail_reply_html_send(callback: CallbackQuery, state: FSMContext):
    try:
        _, kind, acc_id, uid = (callback.data or "").split(":", 3)
        acc_id = int(acc_id)
    except Exception:
        return await callback.answer("Неверные данные", show_alert=True)

    data = await state.get_data()
    async with Session() as session:
        to_email, subject_raw, account_email = await _resolve_reply_recipient(
            session,
            acc_id,
            uid,
            meta=FULL_META.get((acc_id, uid)),
            state_data=data,
            mail_id=data.get("mail_id"),
        )
    if not to_email or "@" not in to_email:
        return await callback.answer(
            "Не вижу email получателя. Откройте карточку письма и «Написать ещё» → HTML.",
            show_alert=True,
        )
    await state.update_data(
        to_email=to_email,
        subject=subject_raw,
        account_email=account_email,
    )

    if kind == "custom":
        await state.set_state(_MailReplyState.waiting_custom_html)
        await callback.message.answer(
            "Отправьте HTML-разметку текстом или .txt файлом\n\n"
            "Чтобы отменить — отправь <code>-</code>.",
            parse_mode="HTML",
        )
        return await callback.answer()

    file_map = {
        "pro": "confirmation.html",
        "go": "confirmation.html",
        "go_new": "confirmation_new.html",
        "pickup": "pickup.html",
        "sms": "sms.html",
        "push": "push.html",
        "back": "back.html",
    }
    filename = file_map.get(kind)
    if not filename:
        return await callback.answer("Неизвестный шаблон", show_alert=True)

    mail_uid = uid
    tg_id = int(callback.from_user.id)
    html_kind_label = {"go_new": "GO(new)"}.get(kind, kind.upper())
    sent_pkg: dict = {}

    async with Session() as session:
        user_pre = await get_or_create_user(session, tg_id)
        from services.aqua_keys import resolve_html_service
        from services.html_templates import html_template_path, service_label_for_path

        html_svc = await resolve_html_service(session, user_pre)
        if not html_template_path(html_svc, filename):
            label = service_label_for_path(html_svc or "—")
            return await callback.answer(
                f"Нет шаблона {filename} для {label}. "
                f"Положи файл в data/HTML/{label}/",
                show_alert=True,
            )

    async def _send() -> tuple[bool, str | None, str | None]:
        async with Session() as session:
            user = await get_or_create_user(session, tg_id)
            acc = (
                await session.execute(sa_select(EmailAccount).where(EmailAccount.id == int(acc_id)))
            ).scalar_one_or_none()
            if not acc:
                return False, "SMTP аккаунт не найден", None

            from services.html_reply import (
                build_offer_html_ctx,
                get_html_sender_name,
                get_html_reply_subject,
                prepare_html_body,
                resolve_aqua_link_for_reply,
            )

            subject = await get_html_reply_subject(
                session,
                user,
                fallback=_reply_subject(subject_raw),
            )
            sender_name = await get_html_sender_name(session, user)

            from services.country_scope import get_scoped_setting

            html_signature = await get_scoped_setting(
                session, user, HTML_SIGNATURE_KEY
            )

            raw_html, tpl_err = await _load_html_template_for_user(session, user, filename)
            if tpl_err or not raw_html:
                return False, tpl_err or "HTML шаблон не найден", None

            from services.placeholders import apply_placeholders

            mail_gen_link = None
            mail_row = None
            try:
                uid_s = (mail_uid or "").strip()
                if uid_s.startswith("S:"):
                    uid_s = uid_s.split(":", 1)[1]
                uid_num = int(uid_s)
                mail_row = (
                    await session.execute(
                        sa_select(IncomingMail)
                        .where(IncomingMail.account_id == int(acc_id))
                        .where(IncomingMail.imap_uid == int(uid_num))
                        .order_by(IncomingMail.id.desc())
                        .limit(1)
                    )
                ).scalars().first()
                if mail_row and mail_row.generated_link:
                    mail_gen_link = str(mail_row.generated_link)
            except Exception:
                pass

            link = await resolve_aqua_link_for_reply(
                session,
                int(user.id),
                account_email=account_email,
                seller_email=to_email,
                mail_generated_link=mail_gen_link,
            )
            ctx = await build_offer_html_ctx(
                session,
                int(user.id),
                to_email,
                link=link,
                mail=mail_row,
                account_email=account_email,
            )
            link = (ctx.get("LINK") or link or "").strip()
            if not (ctx.get("BUYER_NAME") or "").strip() or not (ctx.get("ADDRESS") or "").strip():
                return (
                    False,
                    "Для HTML заполни ФИО и адрес у выбранной команды API "
                    "для текущей рабочей страны.",
                    None,
                )
            html_body = await prepare_html_body(_apply_link(raw_html, link), session, user)
            if html_signature:
                html_body = html_body.replace("{{SIGNATURE}}", str(html_signature))
            html_body = apply_placeholders(html_body, link=link, ctx=ctx)
            sent_pkg["html"] = html_body
            sent_pkg["subject"] = subject

            thread_kw = await _reply_thread_kwargs(
                session,
                acc_id=int(acc_id),
                uid=str(mail_uid),
                mail_id=data.get("mail_id"),
                meta=FULL_META.get((acc_id, mail_uid)),
                mail_row=mail_row,
                user_id=int(user.id),
                to_email=to_email,
                account_email=account_email or getattr(acc, "email", None),
                smtp_password=getattr(acc, "password", None),
            )
            uid_db = int(user.id)
            inbox_em = account_email or getattr(acc, "email", None) or ""
            acc_password = getattr(acc, "password", None) or ""
            try:
                session.expunge(acc)
            except Exception:
                pass
        ok, err, msgid = await send_email_via_account_with_proxy(
            None,
            uid_db,
            acc,
            to_email,
            subject,
            html_body,
            is_html=True,
            sender_name=sender_name,
            fast=True,
            **thread_kw,
        )
        if ok:
            await _remember_reply_msgid(
                user_id=uid_db,
                inbox_email=inbox_em,
                contact_email=to_email,
                msgid=msgid,
                references=thread_kw.get("references"),
                smtp_password=acc_password,
                subject=subject,
            )
        return ok, err, msgid

    meta_fm = FULL_META.get((acc_id, uid)) or {}
    db_user_id: int | None = None
    try:
        async with Session() as session:
            u = await get_or_create_user(session, tg_id)
            db_user_id = int(u.id)
    except Exception:
        pass

    async def _notify_builder() -> ReplyNotifyCtx | None:
        n = await _reply_notify_build_async(
            acc_id=acc_id,
            uid=uid,
            meta=meta_fm,
            state_data=data,
            body_text=f"HTML ({html_kind_label})",
            is_html=True,
            extra_cleanup=[callback.message.message_id],
            user_id=db_user_id,
        )
        if not n:
            return None
        n.html_attachment = sent_pkg.get("html")
        n.html_filename = _html_attachment_filename(sent_pkg.get("subject") or subject_raw)
        return n

    await state.clear()
    if not await _bg_incoming_smtp(callback, tg_id, _send, notify_builder=_notify_builder):
        return


@router.message(_MailReplyState.waiting_choice)
@router.message(_MailReplyState.waiting_text)
async def mail_reply_text(message: Message, state: FSMContext):
    data = await state.get_data()
    text = (message.text or "").strip()
    if text == "-":
        await state.clear()
        return await message.answer(f"{html_emoji('fail')} Отменено.")

    acc_id = int(data.get("acc_id") or 0)
    uid = str(data.get("uid") or "")
    tg_id = int(message.from_user.id)
    body_for_notify = text

    async with Session() as session:
        to_email, subject, _acc_em = await _resolve_reply_recipient(
            session,
            acc_id,
            uid,
            meta=FULL_META.get((acc_id, uid)),
            state_data=data,
            mail_id=data.get("mail_id"),
        )
    if not to_email or "@" not in to_email:
        return await message.answer(
            f"{html_emoji('fail')} Не вижу email получателя. Откройте карточку письма и «Написать ещё» снова."
        )

    out_subject = _reply_subject(subject)

    try:
        from services.incoming_mail_worker import FULL_BODIES, FULL_META as _FM
        from services.users import get_or_create_user

        meta_q = dict(_FM.get((acc_id, uid)) or {})
        parent_body = (FULL_BODIES.get((acc_id, uid)) or "").strip()
        sender_nm = None
        uid_db_q = 0
        inbox_q = ""
        async with Session() as s_b:
            u_q = await get_or_create_user(s_b, tg_id)
            uid_db_q = int(u_q.id)
            sender_nm = getattr(u_q, "sender_name", None)
            if not parent_body and data.get("mail_id"):
                m_b = await _load_incoming_mail_by_id(s_b, int(data["mail_id"]))
                if m_b:
                    parent_body = (m_b.body or "").strip()
                    meta_q.setdefault("from_name", m_b.from_name)
                    meta_q.setdefault("date_str", m_b.date_str)
                    inbox_q = (getattr(m_b, "account_email", None) or "").strip()
            if not inbox_q:
                acc_q = (
                    await s_b.execute(sa_select(EmailAccount).where(EmailAccount.id == acc_id))
                ).scalars().first()
                inbox_q = (getattr(acc_q, "email", None) or "").strip() if acc_q else ""
            text = await compose_threaded_reply_body(
                s_b,
                user_id=uid_db_q,
                to_email=to_email,
                inbox_email=inbox_q or _acc_em or "",
                reply_text=text,
                parent_from_name=meta_q.get("from_name"),
                parent_from_email=to_email,
                parent_date_str=meta_q.get("date_str"),
                parent_body=parent_body,
                sender_name=sender_nm,
            )
    except Exception:
        pass

    async def _send() -> tuple[bool, str | None, str | None]:
        async with Session() as session:
            acc = (
                await session.execute(sa_select(EmailAccount).where(EmailAccount.id == acc_id))
            ).scalar_one_or_none()
            if not acc:
                return False, "SMTP аккаунт не найден в БД.", None
            user = await get_or_create_user(session, tg_id)
            owner_user_id = await _get_acc_owner_user_id(session, acc_id)
            if owner_user_id and int(owner_user_id) != int(user.id):
                return False, "Этот ящик не принадлежит вам.", None
            from services.html_reply import live_account_sender_display_name

            thread_kw = await _reply_thread_kwargs(
                session,
                acc_id=int(acc_id),
                uid=str(uid),
                mail_id=data.get("mail_id"),
                meta=FULL_META.get((acc_id, uid)),
                user_id=int(user.id),
                to_email=to_email,
                account_email=getattr(acc, "email", None),
                smtp_password=getattr(acc, "password", None),
            )
            sender_name = await live_account_sender_display_name(session, user)
            uid_db = int(user.id)
            inbox_em = getattr(acc, "email", None) or ""
            try:
                session.expunge(acc)
            except Exception:
                pass
        ok, err, msgid = await send_email_via_account_with_proxy(
            None,
            uid_db,
            acc,
            to_email,
            out_subject,
            text,
            sender_name=sender_name,
            fast=True,
            **thread_kw,
        )
        if ok:
            await _remember_reply_msgid(
                user_id=uid_db,
                inbox_email=inbox_em,
                contact_email=to_email,
                msgid=msgid,
                references=thread_kw.get("references"),
            )
        return ok, err, msgid

    meta_fm = FULL_META.get((acc_id, uid)) or {}
    state_snap = dict(data)
    db_user_id: int | None = None
    async with Session() as session:
        user = await get_or_create_user(session, tg_id)
        db_user_id = int(user.id)

    async def _notify_builder() -> ReplyNotifyCtx | None:
        return await _reply_notify_build_async(
            acc_id=acc_id,
            uid=uid,
            meta=meta_fm,
            state_data=state_snap,
            body_text=body_for_notify,
            user_id=db_user_id,
        )

    await state.clear()
    if await _bg_message_smtp(message, tg_id, _send, notify_builder=_notify_builder):
        try:
            FULL_META[(acc_id, uid)] = {
                **(FULL_META.get((acc_id, uid)) or {}),
                "last_reply": "pending",
            }
        except Exception:
            pass


@router.message(_MailReplyState.waiting_custom_html)
async def mail_reply_custom_html(message: Message, state: FSMContext):
    """Send user-provided HTML as a reply (CUSTOME-like)."""
    data = await state.get_data()
    text = (message.text or "").strip()
    if text == "-":
        await state.clear()
        return await message.answer(f"{html_emoji('fail')} Отменено.")

    acc_id = int(data.get("acc_id") or 0)
    mail_uid = str(data.get("uid") or "")
    tg_id = int(message.from_user.id)
    html_text = text
    body_for_notify = _preview_reply_body(html_text, is_html=True)
    sent_pkg: dict = {}

    async with Session() as session:
        to_email, subject_raw, account_email = await _resolve_reply_recipient(
            session,
            acc_id,
            mail_uid,
            meta=FULL_META.get((acc_id, mail_uid)),
            state_data=data,
            mail_id=data.get("mail_id"),
        )
    if not to_email or "@" not in to_email:
        return await message.answer(
            f"{html_emoji('fail')} Не вижу email получателя. Откройте карточку письма снова."
        )

    async def _send() -> tuple[bool, str | None, str | None]:
        async with Session() as session:
            user = await get_or_create_user(session, tg_id)
            acc = (
                await session.execute(sa_select(EmailAccount).where(EmailAccount.id == acc_id))
            ).scalar_one_or_none()
            if not acc:
                return False, "SMTP аккаунт не найден в БД.", None

            from services.html_reply import (
                build_offer_html_ctx,
                get_html_sender_name,
                get_html_reply_subject,
                prepare_html_body,
                resolve_aqua_link_for_reply,
            )

            subject = await get_html_reply_subject(
                session,
                user,
                fallback=_reply_subject(subject_raw),
            )
            sender_name = await get_html_sender_name(session, user)

            from services.country_scope import get_scoped_setting

            html_signature = await get_scoped_setting(
                session, user, HTML_SIGNATURE_KEY
            )

            from services.placeholders import apply_placeholders

            mail_gen_link = None
            mail_row = None
            try:
                uid_s = (mail_uid or "").strip()
                if uid_s.startswith("S:"):
                    uid_s = uid_s.split(":", 1)[1]
                uid_num = int(uid_s)
                mail_row = (
                    await session.execute(
                        sa_select(IncomingMail)
                        .where(IncomingMail.account_id == int(acc_id))
                        .where(IncomingMail.imap_uid == int(uid_num))
                        .order_by(IncomingMail.id.desc())
                        .limit(1)
                    )
                ).scalars().first()
                if mail_row and mail_row.generated_link:
                    mail_gen_link = str(mail_row.generated_link)
            except Exception:
                pass

            link = await resolve_aqua_link_for_reply(
                session,
                int(user.id),
                account_email=account_email,
                seller_email=to_email,
                mail_generated_link=mail_gen_link,
            )
            ctx = await build_offer_html_ctx(
                session,
                int(user.id),
                to_email,
                link=link,
                mail=mail_row,
                account_email=account_email,
            )
            link = (ctx.get("LINK") or link or "").strip()
            if not (ctx.get("BUYER_NAME") or "").strip() or not (ctx.get("ADDRESS") or "").strip():
                return (
                    False,
                    "Для HTML заполни ФИО и адрес у выбранной команды API "
                    "для текущей рабочей страны.",
                    None,
                )
            html_body = await prepare_html_body(_apply_link(html_text, link), session, user)
            if html_signature:
                html_body = html_body.replace("{{SIGNATURE}}", str(html_signature))
            html_body = apply_placeholders(html_body, link=link, ctx=ctx)
            sent_pkg["html"] = html_body
            sent_pkg["subject"] = subject

            thread_kw = await _reply_thread_kwargs(
                session,
                acc_id=int(acc_id),
                uid=str(mail_uid),
                mail_id=data.get("mail_id"),
                meta=FULL_META.get((acc_id, mail_uid)),
                mail_row=mail_row,
                user_id=int(user.id),
                to_email=to_email,
                account_email=account_email or getattr(acc, "email", None),
                smtp_password=getattr(acc, "password", None),
            )
            uid_db = int(user.id)
            inbox_em = account_email or getattr(acc, "email", None) or ""
            acc_password = getattr(acc, "password", None) or ""
            try:
                session.expunge(acc)
            except Exception:
                pass
        ok, err, msgid = await send_email_via_account_with_proxy(
            None,
            uid_db,
            acc,
            to_email,
            subject,
            html_body,
            is_html=True,
            sender_name=sender_name,
            fast=True,
            **thread_kw,
        )
        if ok:
            await _remember_reply_msgid(
                user_id=uid_db,
                inbox_email=inbox_em,
                contact_email=to_email,
                msgid=msgid,
                references=thread_kw.get("references"),
                smtp_password=acc_password,
                subject=subject,
            )
        return ok, err, msgid

    meta_fm = FULL_META.get((acc_id, mail_uid)) or {}
    db_user_id: int | None = None
    async with Session() as session:
        user = await get_or_create_user(session, tg_id)
        db_user_id = int(user.id)

    async def _notify_builder() -> ReplyNotifyCtx | None:
        n = await _reply_notify_build_async(
            acc_id=acc_id,
            uid=mail_uid,
            meta=meta_fm,
            state_data=data,
            body_text=body_for_notify,
            is_html=True,
            user_id=db_user_id,
        )
        if not n:
            return None
        n.html_attachment = sent_pkg.get("html")
        n.html_filename = _html_attachment_filename(sent_pkg.get("subject") or subject_raw)
        return n

    await state.clear()
    await _bg_message_smtp(message, tg_id, _send, notify_builder=_notify_builder)


@router.callback_query(F.data.startswith("mail_info:"))
async def cb_mail_info(callback: CallbackQuery):
    try:
        _, acc_id, uid = (callback.data or "").split(":", 2)
        acc_id = int(acc_id)
    except Exception:
        return await callback.answer("Неверные данные", show_alert=True)

    # ✅ Основной источник данных — БД (IncomingMail).
    # FULL_META может быть очищен при рестартах, поэтому здесь всегда...
    meta = FULL_META.get((acc_id, uid)) or {}
    inbox_email = _canon_email(meta.get("account_email") or "")
    contact_email = _canon_email(meta.get("from_email") or "")
    subject = (meta.get("subject") or "").strip()
    ad_url = (meta.get("ad_url") or "").strip()
    gen_link = (meta.get("generated_link") or "").strip()

    mail_db_id: int | None = None
    mail_body: str = ""
    mail_date: str = ""
    mail_from_name: str = ""
    resolved_offer_id: int | None = None

    offer_title_full = offer_price = offer_link_full = offer_photo = offer_person = ""

    conv_ad = conv_gen = ""
    offer_title = offer_link = ""
    offer_emails_cnt = 0
    offer_link_by_email = ""
    offer_emails_cnt_by_email = 0

    async with Session() as session:
        owner_user_id = await _get_acc_owner_user_id(session, acc_id)
        if owner_user_id:
            # 0) Ищем письмо в БД
            mail = (
                await session.execute(
                    sa_select(IncomingMail)
                    .where(IncomingMail.account_id == int(acc_id))
                    .where(IncomingMail.imap_uid == int(uid))
                    .limit(1)
                )
            ).scalars().first()
            if mail:
                mail_db_id = int(getattr(mail, "id", 0) or 0) or None
                inbox_email = _canon_email(getattr(mail, "account_email", "") or "") or inbox_email
                contact_email = _canon_email(getattr(mail, "from_email", "") or "") or contact_email
                mail_from_name = (getattr(mail, "from_name", "") or "")
                subject = (getattr(mail, "subject", "") or "").strip() or subject
                mail_date = (getattr(mail, "date_str", "") or "")
                mail_body = (getattr(mail, "body", "") or "")
                ad_url = (getattr(mail, "ad_url", "") or "").strip() or ad_url
                gen_link = (getattr(mail, "generated_link", "") or "").strip() or gen_link
                resolved_offer_id = int(getattr(mail, "resolved_offer_id", 0) or 0) or None

            conv = await _get_convlink(
                session,
                user_id=owner_user_id,
                inbox_email=inbox_email,
                contact_email=contact_email,
            )
            if conv:
                conv_ad = (conv.ad_url or "").strip()
                conv_gen = (conv.generated_link or "").strip()

            # 0.1) Если письмо связано с Offer — показываем полные данные из Offer
            if resolved_offer_id:
                off = (
                    await session.execute(
                        sa_select(Offer).where(Offer.id == int(resolved_offer_id)).where(Offer.user_id == int(owner_user_id)).limit(1)
                    )
                ).scalars().first()
                if off:
                    offer_title_full = (getattr(off, "title", "") or "")
                    offer_price = (getattr(off, "price", "") or "")
                    offer_link_full = (getattr(off, "link", "") or "")
                    offer_photo = (getattr(off, "photo", "") or "")
                    offer_person = (getattr(off, "person_name", "") or "")

            if subject:
                subj_norm = re.sub(
                    r"^(re|aw|fw|fwd)\s*:\s*",
                    "",
                    subject,
                    flags=re.I,
                ).strip()
                m = re.search(r"\bOFFER\s*:\s*(.+)$", subj_norm, flags=re.I)
                offer_title = (m.group(1).strip() if m else subj_norm)

                row = (
                    await session.execute(
                        sa_select(Offer.id, Offer.link)
                        .where(Offer.user_id == int(owner_user_id))
                        .where(func.lower(Offer.title).like(f"%{offer_title.lower()}%"))
                        .order_by(Offer.id.desc())
                        .limit(1)
                    )
                ).first()
                if row:
                    oid, olink = row
                    offer_link = (olink or "").strip()
                    offer_emails_cnt = (
                        await session.execute(
                            sa_select(func.count(OfferEmail.id)).where(
                                OfferEmail.offer_id == int(oid)
                            )
                        )
                    ).scalar_one() or 0

            # если по теме ничего не нашлось — ищем по email отправителя
            if contact_email:
                offer_obj, cnt = await _offer_by_sender_email(
                    session, int(owner_user_id), contact_email
                )
                if offer_obj is not None:
                    offer_link_by_email = (
                        getattr(offer_obj, "link", "") or ""
                    ).strip()
                    offer_emails_cnt_by_email = int(cnt or 0)

    # Показываем "фул данные" по письму (основное из IncomingMail + привязанные сущности).
    # Дизайн не меняем — просто текст.
    body_preview = (mail_body or "").strip()
    if body_preview and len(body_preview) > 1800:
        body_preview = body_preview[:1800] + "…"

    text = (
        f"{html_emoji('info')} <b>Информация по письму</b>\n\n"
        f"<b>Mail ID:</b> <code>{mail_db_id or '—'}</code>\n"
        f"<b>Inbox:</b> <code>{_e(inbox_email) or '—'}</code>\n"
        f"<b>From:</b> <code>{_e(contact_email) or '—'}</code>\n"
        f"<b>From name:</b> <code>{_e(mail_from_name) or '—'}</code>\n"
        f"<b>Subject:</b> <code>{_e(subject) or '—'}</code>\n\n"
        f"<b>Date:</b> <code>{_e(mail_date) or '—'}</code>\n\n"
        f"<b>Meta ad_url:</b> <code>{_e(ad_url) or '—'}</code>\n"
        f"<b>Meta generated_link:</b> <code>{_e(gen_link) or '—'}</code>\n"
        f"<b>DB conv ad_url:</b> <code>{_e(conv_ad) or '—'}</code>\n"
        f"<b>DB conv generated_link:</b> <code>{_e(conv_gen) or '—'}</code>\n\n"
        f"<b>Resolved offer_id:</b> <code>{resolved_offer_id or '—'}</code>\n"
        f"<b>Offer.title:</b> <code>{_e(offer_title_full) or '—'}</code>\n"
        f"<b>Offer.price:</b> <code>{_e(offer_price) or '—'}</code>\n"
        f"<b>Offer.link:</b> <code>{_e(offer_link_full) or '—'}</code>\n"
        f"<b>Offer.photo:</b> <code>{_e(offer_photo) or '—'}</code>\n"
        f"<b>Offer.person_name:</b> <code>{_e(offer_person) or '—'}</code>\n\n"
        f"<b>Offer title from subject:</b> <code>{_e(offer_title) or '—'}</code>\n"
        f"<b>Offer.link (by title):</b> <code>{_e(offer_link) or '—'}</code>\n"
        f"<b>Offer emails count:</b> <code>{offer_emails_cnt}</code>\n"
        f"<b>Offer.link (by sender email):</b> <code>{_e(offer_link_by_email) or '—'}</code>\n"
        f"<b>Offer emails count (by sender email):</b> <code>{offer_emails_cnt_by_email}</code>\n"
        + ("\n<b>Body preview:</b>\n<blockquote><code>" + _e(body_preview) + "</code></blockquote>" if body_preview else "")
    )
    await callback.message.answer(text, parse_mode="HTML", disable_web_page_preview=True)
    await callback.answer()


# =========================
# Offer price edit (кнопка "Цена" на pinned карточке)
# =========================
# Offer price → пересоздать AQUA-ссылку
# =========================


def _format_aqua_price_from_input(text: str, *, previous: str | None = None) -> str | None:
    """Парсинг цены для GOO: по умолчанию EUR (Бельгия)."""
    raw = (text or "").strip().replace(",", ".")
    if not raw:
        return None
    m = re.search(r"([\d.]+)", raw)
    if not m:
        return None
    try:
        num = float(m.group(1))
    except ValueError:
        return None
    if num < 0:
        return None

    prev = (previous or "").upper()
    suffix_m = re.search(r"([A-Za-z]{2,4}|€)\s*$", raw.strip())
    if suffix_m:
        suf = suffix_m.group(1).upper()
        if suf in {"€", "EUR"}:
            return f"{num:.2f} EUR"
        if suf == "CHF":
            return f"{num:.2f} EUR"
    if "EUR" in prev or "€" in (previous or ""):
        return f"{num:.2f} EUR"
    return f"{num:.2f} EUR"


async def _resolve_offer_dialog_emails(session, user_id: int, offer_id: int) -> tuple[str, str]:
    """inbox (наш ящик) и contact (продавец) по OfferEmail + ConversationLink + IncomingMail."""
    emails = (
        await session.execute(
            sa_select(OfferEmail.email).where(OfferEmail.offer_id == int(offer_id)).limit(8)
        )
    ).scalars().all()
    for em in emails:
        contact_keys = _email_keys(str(em or ""))
        if not contact_keys:
            continue
        conv = (
            await session.execute(
                sa_select(ConversationLink)
                .where(ConversationLink.user_id == int(user_id))
                .where(func.lower(ConversationLink.from_email).in_(contact_keys))
                .order_by(ConversationLink.id.desc())
                .limit(1)
            )
        ).scalars().first()
        if conv and (conv.account_email or "").strip():
            return _canon_email(conv.account_email or ""), _canon_email(conv.from_email or "")
    mail = (
        await session.execute(
            sa_select(IncomingMail)
            .where(IncomingMail.user_id == int(user_id))
            .where(IncomingMail.resolved_offer_id == int(offer_id))
            .order_by(IncomingMail.id.desc())
            .limit(1)
        )
    ).scalars().first()
    if mail:
        inbox = _canon_email(mail.account_email or "")
        contact = _canon_email(mail.from_email or "")
        if inbox and contact:
            return inbox, contact
    conv_pin = (
        await session.execute(
            sa_select(ConversationLink)
            .where(ConversationLink.user_id == int(user_id))
            .where(ConversationLink.pinned_offer_id == int(offer_id))
            .order_by(ConversationLink.id.desc())
            .limit(1)
        )
    ).scalars().first()
    if conv_pin:
        inbox = _canon_email(conv_pin.account_email or "")
        contact = _canon_email(conv_pin.from_email or "")
        if inbox and contact:
            return inbox, contact
    return "", ""


async def _regenerate_aqua_link_after_price(
    bot,
    chat_id: int,
    tg_user_id: int,
    *,
    offer_id: int,
    new_price: str,
    anchor_message_id: int | None,
    inbox_email: str,
    contact_email: str,
) -> tuple[bool, str]:
    card: dict = {}
    async with Session() as session:
        user = await get_or_create_user(session, int(tg_user_id))
        offer = (
            await session.execute(
                sa_select(Offer)
                .where(Offer.id == int(offer_id))
                .where(Offer.user_id == int(user.id))
                .limit(1)
            )
        ).scalars().first()
        if not offer:
            return False, "Оффер не найден"

        offer.price = new_price
        try:
            from services.offer_storage import parse_offer_raw
            import json as _json

            raw = parse_offer_raw(getattr(offer, "raw_json", None)) or {}
            if isinstance(raw, dict):
                raw["item_price"] = new_price
                offer.raw_json = _json.dumps(raw, ensure_ascii=False)
        except Exception:
            pass
        await session.flush()

        try:
            aqua_url = await aqua_generate_for_offer(
                session, user, offer, price=new_price, force_no_parse=True
            )
        except AquaError as e:
            await session.rollback()
            return False, str(e)

        from services.offer_storage import set_offer_aqua_pin

        set_offer_aqua_pin(offer, link=aqua_url, price=new_price)
        ad_url = (offer.link or "").strip()
        if not inbox_email or not contact_email:
            inbox_email, contact_email = await _resolve_offer_dialog_emails(
                session, int(user.id), int(offer.id)
            )
        if inbox_email and contact_email:
            await _upsert_convlink(
                session,
                user_id=int(user.id),
                inbox_email=inbox_email,
                contact_email=contact_email,
                ad_url=ad_url or None,
                generated_link=aqua_url,
                generated_price=new_price,
                pinned_offer_id=int(offer.id),
            )
        await _pin_generated_link_on_dialog_mails(
            session,
            user_id=int(user.id),
            inbox_email=inbox_email,
            contact_email=contact_email,
            generated_link=aqua_url,
            generated_price=new_price,
            offer_id=int(offer.id),
        )
        if contact_email:
            from services.email_address import dialog_email_match_keys

            contact_keys = dialog_email_match_keys(contact_email)
            if contact_keys:
                await session.execute(
                    sa_update(ConversationLink)
                    .where(ConversationLink.user_id == int(user.id))
                    .where(func.lower(ConversationLink.from_email).in_(contact_keys))
                    .values(
                        generated_link=aqua_url,
                        last_generated_price=new_price[:64],
                        pinned_offer_id=int(offer.id),
                    )
                )
        await session.execute(
            sa_update(ConversationLink)
            .where(ConversationLink.user_id == int(user.id))
            .where(ConversationLink.pinned_offer_id == int(offer.id))
            .values(generated_link=aqua_url, last_generated_price=new_price[:64])
        )
        await session.execute(
            sa_update(IncomingMail)
            .where(IncomingMail.user_id == int(user.id))
            .where(IncomingMail.resolved_offer_id == int(offer.id))
            .values(generated_link=aqua_url, offer_price=new_price)
        )
        await session.commit()

        card = {
            "offer_title": offer_effective_title(offer) or None,
            "offer_price": new_price,
            "photo_url": offer_effective_photo(offer) or None,
            "profile_display": (
                await get_user_aqua_profile_display(session, user) or ""
            ).strip()
            or None,
            "service_code": (await get_user_aqua_service(session, user) or "").strip(),
            "link": aqua_url,
            "offer_id": int(offer.id),
            "inbox_label": (getattr(user, "sender_name", None) or "").strip() or None,
        }

    await _send_generated_link_card_to_chat(
        bot,
        int(chat_id),
        offer_title=card["offer_title"],
        offer_price=card["offer_price"],
        photo_url=card["photo_url"],
        profile_display=card["profile_display"],
        service_code=card["service_code"],
        link=card["link"],
        offer_id=card["offer_id"],
        anchor_message_id=anchor_message_id,
        account_email=inbox_email or None,
        contact_email=contact_email or None,
        inbox_label=card["inbox_label"],
    )
    return True, new_price


class _OfferPriceState(StatesGroup):
    waiting_price = State()


@router.callback_query(F.data.startswith("offer_price:"))
async def cb_offer_price(callback: CallbackQuery, state: FSMContext):
    try:
        offer_id = int((callback.data or "").split(":", 1)[1])
    except Exception:
        return await callback.answer("Неверный ID", show_alert=True)

    anchor: int | None = None
    rt = callback.message.reply_to_message if callback.message else None
    if rt and getattr(rt, "message_id", None):
        anchor = int(rt.message_id)

    inbox_email = contact_email = ""
    async with Session() as session:
        user = await get_or_create_user(session, int(callback.from_user.id))
        offer = (
            await session.execute(
                sa_select(Offer)
                .where(Offer.id == int(offer_id))
                .where(Offer.user_id == int(user.id))
                .limit(1)
            )
        ).scalars().first()
        if not offer:
            return await callback.answer("Оффер не найден", show_alert=True)
        current = (offer.price or "—").strip() or "—"
        inbox_email, contact_email = await _resolve_offer_dialog_emails(session, int(user.id), int(offer_id))
        if not anchor and inbox_email and contact_email:
            conv = await _load_convlink_for_reply(
                session,
                user_id=int(user.id),
                inbox_email=inbox_email,
                contact_email=contact_email,
            )
            if conv and getattr(conv, "tg_message_id", None):
                anchor = int(conv.tg_message_id)

    await state.clear()
    await state.set_state(_OfferPriceState.waiting_price)
    await state.update_data(
        offer_id=offer_id,
        chat_id=int(callback.message.chat.id),
        anchor_message_id=anchor,
        inbox_email=inbox_email,
        contact_email=contact_email,
    )

    await callback.message.answer(
        f"{html_emoji('price')} <b>Цена</b>\n\n"
        f"Текущая цена: <code>{_e(current)}</code>\n\n"
        "Отправь новую цену (например: <code>500</code> или <code>500.00 EUR</code>).\n"
        "Бот пересоздаст ссылку и отправит её к письму.\n\n"
        "Чтобы отменить — отправь <code>-</code>.",
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(_OfferPriceState.waiting_price)
async def offer_price_set(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    if text == "-":
        await state.clear()
        return await message.answer(f"{html_emoji('fail')} Отменено.")

    data = await state.get_data()
    offer_id = int(data.get("offer_id") or 0)
    if not offer_id:
        await state.clear()
        return await message.answer(f"{html_emoji('fail')} Нет offer_id.")

    prev_price = ""
    async with Session() as session:
        offer = (
            await session.execute(sa_select(Offer).where(Offer.id == offer_id).limit(1))
        ).scalars().first()
        if offer:
            prev_price = (offer.price or "").strip()

    new_price = _format_aqua_price_from_input(text, previous=prev_price)
    if not new_price:
        return await message.answer(
            f"{html_emoji('fail')} Введи число (пример: <code>500</code> или <code>500.00 EUR</code>) или <code>-</code> для отмены.",
            parse_mode="HTML",
        )

    chat_id = int(data.get("chat_id") or message.chat.id)
    anchor = data.get("anchor_message_id")
    anchor_id = int(anchor) if anchor else None
    inbox_email = _canon_email(str(data.get("inbox_email") or ""))
    contact_email = _canon_email(str(data.get("contact_email") or ""))
    tg_id = int(message.from_user.id)

    await state.clear()

    if bg_is_running(tg_id, "aqua_link"):
        return await message.answer(f"{html_emoji('wait')} Ссылка уже создаётся… подождите.")

    await message.answer(f"{html_emoji('wait')} Пересоздаю ссылку с новой ценой…")

    bot = message.bot

    async def _job() -> None:
        ok, info = await _regenerate_aqua_link_after_price(
            bot,
            chat_id,
            tg_id,
            offer_id=offer_id,
            new_price=new_price,
            anchor_message_id=anchor_id,
            inbox_email=inbox_email,
            contact_email=contact_email,
        )
        if ok:
            await bot.send_message(
                chat_id,
                f"{html_emoji('ok')} Цена обновлена: <code>{_e(info)}</code>\nНовая ссылка прикреплена к письму.",
                parse_mode="HTML",
                reply_to_message_id=anchor_id,
            )
        else:
            await bot.send_message(
                chat_id,
                f"{html_emoji('fail')} Не удалось пересоздать ссылку:\n<code>{_e(info)}</code>",
                parse_mode="HTML",
            )

    if not bg_start(tg_id, "aqua_link", _job()):
        await message.answer(f"{html_emoji('wait')} Ссылка уже создаётся…")
