# handlers/mail_templates.py
from __future__ import annotations

import logging
from typing import List

from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext

from sqlalchemy import select

from database import Session
from models import EmailAccount, User

from services.incoming_mail_worker import FULL_META
from services.smtp_proxy_send import send_email_via_account_with_proxy
from handlers.templates import load_templates, TemplateItem
from handlers.incoming_mail import _bg_incoming_smtp, _reply_notify_build_async
from services.users import get_or_create_user
from models import IncomingMail
from utils.ui_emoji import html_emoji, inline_button, menu_path, toast, msg_fail, msg_ok, msg_wait, msg_warn

router = Router()
logger = logging.getLogger(__name__)


def _templates_kb(
    items: List[TemplateItem],
    acc_id: int,
    uid: str,
    *,
    mail_id: int | None = None,
) -> InlineKeyboardMarkup:
    rows: List[List[InlineKeyboardButton]] = []

    for i, t in enumerate(items[:30]):
        label = (t.title or f"Пресет #{i + 1}").strip()[:40]
        if mail_id:
            cb = f"mail_tmpl_send:{i}:m{int(mail_id)}"
        else:
            cb = f"mail_tmpl_send:{i}:{acc_id}:{uid}"
        rows.append([InlineKeyboardButton(text=label, callback_data=cb)])

    close_cb = f"mail_tmpl_close:m{int(mail_id)}" if mail_id else f"mail_tmpl_close:{acc_id}:{uid}"
    rows.append([inline_button("hide", "Скрыть", callback_data=close_cb)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _safe_re_subject(subject: str) -> str:
    s = (subject or "").strip()
    if not s:
        return "Re: message"
    sl = s.lower()
    if sl.startswith("re:"):
        return s
    return f"Re: {s}"


def _render_subject_with_offer(subject_template: str, offer_title: str) -> str:
    from services.subject_offer import render_subject_with_offer

    return render_subject_with_offer(
        (subject_template or "").strip() or "Re: OFFER",
        (offer_title or "").strip() or "OFFER",
    )


def _parse_uid(uid: str) -> int | None:
    """IncomingMail stores imap_uid as int. UID in callbacks can be like '123', 'S:123', 'X0:123'."""
    try:
        u = (uid or "").strip()
        if ":" in u:
            u = u.rsplit(":", 1)[-1]
        return int(u)
    except Exception:
        return None


def _meta_dict_from_mail(m: IncomingMail) -> dict:
    from services.email_address import extract_email_address

    return {
        "from_email": extract_email_address(m.from_email or ""),
        "from_name": (m.from_name or "").strip(),
        "subject": m.subject or "",
        "account_email": extract_email_address(m.account_email or ""),
        "date_str": m.date_str or "",
        "rfc_message_id": (getattr(m, "rfc_message_id", None) or "").strip(),
        "rfc_in_reply_to": (getattr(m, "rfc_in_reply_to", None) or "").strip(),
        "rfc_references": (getattr(m, "rfc_references", None) or "").strip(),
        "_acc_id": int(m.account_id),
        "_uid": str(m.imap_uid),
        "_mail_id": int(m.id),
    }


async def _load_meta_by_mail_id(mail_id: int) -> dict | None:
    try:
        mid = int(mail_id)
    except (TypeError, ValueError):
        return None
    async with Session() as session:
        m = (
            await session.execute(
                select(IncomingMail).where(IncomingMail.id == mid).limit(1)
            )
        ).scalars().first()
    if not m:
        return None
    return _meta_dict_from_mail(m)


async def _load_meta_from_db(acc_id: int, uid: str) -> dict | None:
    """Fallback after redeploy: FULL_META в RAM очищается, письмо ищем в Postgres."""
    uid_num = _parse_uid(uid)
    if uid_num is None:
        return None

    async with Session() as session:
        m = (
            await session.execute(
                select(IncomingMail)
                .where(IncomingMail.account_id == int(acc_id))
                .where(IncomingMail.imap_uid == int(uid_num))
                .order_by(IncomingMail.id.desc())
                .limit(1)
            )
        ).scalars().first()

    if not m:
        return None

    return _meta_dict_from_mail(m)


async def _resolve_mail_meta(
    *,
    acc_id: int | None = None,
    uid: str | None = None,
    mail_id: int | None = None,
    state_data: dict | None = None,
    tg_message_id: int | None = None,
) -> dict | None:
    """Письмо для пресетов: RAM → Postgres по mail_id → acc+uid → id карточки TG."""
    state_data = state_data or {}
    mid = mail_id or state_data.get("mail_id")
    if mid:
        meta = await _load_meta_by_mail_id(int(mid))
        if meta:
            return meta

    acc = int(acc_id or state_data.get("acc_id") or 0)
    uid_s = str(uid or state_data.get("uid") or "").strip()
    if acc and uid_s:
        meta = FULL_META.get((acc, uid_s)) or await _load_meta_from_db(acc, uid_s)
        if meta:
            return meta

    if tg_message_id:
        async with Session() as session:
            m = (
                await session.execute(
                    select(IncomingMail)
                    .where(IncomingMail.telegram_message_id == int(tg_message_id))
                    .order_by(IncomingMail.id.desc())
                    .limit(1)
                )
            ).scalars().first()
        if m:
            return _meta_dict_from_mail(m)

    return None


_STALE_MAIL_MSG = (
    "Письмо не найдено в базе (не из‑за возраста). "
    "Откройте карточку снова через «Написать ещё» или дождитесь нового входящего."
)


 


@router.callback_query(F.data.startswith("mail_tmpl_open:"))
async def mail_tmpl_open(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    acc_id: int | None = None
    uid: str | None = None
    mail_id: int | None = None
    try:
        parts = (callback.data or "").split(":")
        if len(parts) == 2 and parts[1].startswith("m"):
            mail_id = int(parts[1][1:])
        elif len(parts) >= 3:
            acc_id = int(parts[1])
            uid = ":".join(parts[2:])
    except Exception:
        return await callback.answer("Неверные данные", show_alert=True)

    card_mid = int(callback.message.message_id) if callback.message else None
    meta = await _resolve_mail_meta(
        acc_id=acc_id,
        uid=uid,
        mail_id=mail_id,
        state_data=data,
        tg_message_id=card_mid,
    )
    if not meta:
        return await callback.answer(_STALE_MAIL_MSG, show_alert=True)

    acc_id = int(meta.get("_acc_id") or acc_id or 0)
    uid = str(meta.get("_uid") or uid or "")
    mail_id = int(meta.get("_mail_id") or mail_id or 0) or None

    items = await load_templates(callback.from_user.id)
    if not items:
        return await callback.answer(f"Нет шаблонов. Добавь их в {html_emoji('burst')} Шаблоны", show_alert=True)

    text = "Нажмите на пресет для отправки"
    await callback.message.answer(
        text,
        reply_markup=_templates_kb(items, acc_id, uid, mail_id=mail_id),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("mail_tmpl_close:"))
async def mail_tmpl_close(callback: CallbackQuery):
    await callback.answer("Ок", show_alert=False)


@router.callback_query(F.data.startswith("mail_tmpl_send:"))
async def mail_tmpl_send(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    acc_id: int | None = None
    uid: str | None = None
    mail_id: int | None = None
    try:
        parts = (callback.data or "").split(":")
        idx = int(parts[1])
        if len(parts) == 3 and parts[2].startswith("m"):
            mail_id = int(parts[2][1:])
        elif len(parts) >= 4:
            acc_id = int(parts[2])
            uid = ":".join(parts[3:])
        else:
            raise ValueError("bad callback")
    except Exception:
        return await callback.answer("Неверный формат", show_alert=True)

    card_mid = int(callback.message.message_id) if callback.message else None
    meta = await _resolve_mail_meta(
        acc_id=acc_id,
        uid=uid,
        mail_id=mail_id,
        state_data=data,
        tg_message_id=card_mid,
    )
    if not meta:
        return await callback.answer(_STALE_MAIL_MSG, show_alert=True)

    acc_id = int(meta.get("_acc_id") or acc_id or 0)
    uid = str(meta.get("_uid") or uid or "")

    from services.email_address import extract_email_address, is_valid_smtp_recipient

    to_email = extract_email_address(meta.get("from_email") or "")
    if not is_valid_smtp_recipient(to_email):
        return await callback.answer("Не найден email получателя", show_alert=True)

    items = await load_templates(callback.from_user.id)
    if not items:
        return await callback.answer(f"Нет шаблонов. Добавь их в {html_emoji('burst')} Шаблоны", show_alert=True)

    if idx < 0 or idx >= len(items):
        return await callback.answer("Шаблон не найден", show_alert=True)

    tpl = items[idx]
    body = (tpl.text or "").strip()
    if not body:
        return await callback.answer("Пустой шаблон", show_alert=True)

    from handlers.incoming_mail import _reply_subject

    subject_orig = (meta.get("subject") or "").strip()
    subject = _reply_subject(subject_orig)
    tg_id = callback.from_user.id
    body_copy = body
    try:
        from services.email_threading import format_gmail_style_reply_body
        from services.incoming_mail_worker import FULL_BODIES

        parent_body = ""
        if mail_id or meta.get("_mail_id"):
            try:
                mid_load = int(mail_id or meta.get("_mail_id"))
            except Exception:
                mid_load = None
            if mid_load:
                async with Session() as s_body:
                    m_body = (
                        await s_body.execute(
                            select(IncomingMail).where(IncomingMail.id == mid_load).limit(1)
                        )
                    ).scalars().first()
                    if m_body:
                        parent_body = (m_body.body or "").strip()
        if not parent_body and acc_id and uid:
            parent_body = (FULL_BODIES.get((int(acc_id), str(uid))) or "").strip()
        body_copy = format_gmail_style_reply_body(
            body,
            parent_from_name=meta.get("from_name"),
            parent_from_email=to_email,
            parent_date_str=meta.get("date_str"),
            parent_body=parent_body,
        )
    except Exception:
        logger.exception("gmail-style quote for preset failed")

    async def _send() -> tuple[bool, str | None, str | None]:
        async with Session() as session:
            acc = (await session.execute(select(EmailAccount).where(EmailAccount.id == acc_id))).scalars().first()
            if not acc:
                return False, "SMTP аккаунт не найден", None
            user = (
                await session.execute(select(User).where(User.telegram_id == int(tg_id)))
            ).scalars().first()
            if not user:
                return False, "Пользователь не найден", None
            # Тема только Re: исходного треда — иначе Gmail рвёт диалог.
            out_subject = subject
            from handlers.incoming_mail import (
                _load_incoming_mail_by_id,
                _load_incoming_mail_for_uid,
                _reply_thread_kwargs,
            )
            from services.html_reply import account_sender_display_name

            mid = mail_id or meta.get("_mail_id")
            try:
                mid_i = int(mid) if mid else None
            except Exception:
                mid_i = None
            mail_row = await _load_incoming_mail_by_id(session, mid_i) if mid_i else None
            if mail_row is None and acc_id and uid:
                mail_row = await _load_incoming_mail_for_uid(session, int(acc_id), str(uid))
            if mail_row:
                subj_src = (
                    (mail_row.subject or "").strip()
                    or (mail_row.outgoing_mail_subject or "").strip()
                    or subject_orig
                )
                out_subject = _reply_subject(subj_src)
            thread_kw = await _reply_thread_kwargs(
                session,
                acc_id=int(acc_id),
                uid=str(uid or ""),
                mail_id=mid_i,
                meta=meta,
                mail_row=mail_row,
                user_id=int(user.id),
                to_email=to_email,
                account_email=(meta.get("account_email") or getattr(acc, "email", None) or ""),
            )
            if not thread_kw.get("in_reply_to"):
                logger.error(
                    "preset reply WITHOUT In-Reply-To to=%s acc=%s mail_id=%s uid=%s — abort to avoid split thread",
                    to_email,
                    acc_id,
                    mid_i,
                    uid,
                )
                return False, "Нет Message-ID диалога (откройте карточку письма снова)", None
            logger.info(
                "preset SMTP thread to=%s in_reply_to=%s refs=%s subj=%r",
                to_email,
                (thread_kw.get("in_reply_to") or "")[:100],
                (thread_kw.get("references") or "")[:180],
                (out_subject or "")[:80],
            )
            is_html_body = "<html" in body_copy.lower() or "<body" in body_copy.lower()
            sender_name = account_sender_display_name(user)
            uid_db = int(user.id)
            inbox_em = getattr(acc, "email", None) or meta.get("account_email") or ""
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
            out_subject,
            body_copy,
            sender_name=sender_name,
            is_html=is_html_body or None,
            fast=True,
            **thread_kw,
        )
        if ok and msgid:
            try:
                from database import db_session
                from services.email_threading import remember_dialog_outbound
                from services.smtp_delivery_verify import fetch_real_sent_message_id

                real_mid = await fetch_real_sent_message_id(
                    inbox_em,
                    acc_password,
                    subject=out_subject,
                    to_email=to_email,
                    local_message_id=msgid,
                    wait_sec=2.0,
                )
                store_mid = real_mid or msgid
                async with db_session() as s2:
                    await remember_dialog_outbound(
                        s2,
                        user_id=uid_db,
                        inbox_email=inbox_em,
                        contact_email=to_email,
                        outbound_message_id=store_mid,
                        references_header=thread_kw.get("references"),
                    )
                    await s2.commit()
            except Exception:
                logger.exception("remember template reply msgid failed")
        return ok, err, msgid

    data = await state.get_data()
    db_user_id: int | None = None
    try:
        async with Session() as session:
            u = await get_or_create_user(session, int(tg_id))
            db_user_id = int(u.id)
    except Exception:
        pass
    notify = await _reply_notify_build_async(
        acc_id=acc_id,
        uid=str(uid),
        meta=meta or {},
        state_data=data,
        body_text=body,
        is_preset=True,
        extra_cleanup=[callback.message.message_id],
        user_id=db_user_id,
    )
    await state.clear()
    if not await _bg_incoming_smtp(callback, tg_id, _send, notify=notify):
        return
    logger.info("MAIL_TEMPLATE queued to=%s acc_id=%s uid=%s idx=%s", to_email, acc_id, uid, idx)
