"""Тема и имя отправителя для HTML-ответов (отдельно от рассылки с OFFER)."""

from __future__ import annotations

import re

from models import User
from services.html_spoof import apply_nick_to_html, get_spoof_display_name
from services.subject_offer import sanitize_email_subject
from services.user_settings import get_user_setting

# как в handlers/settings.py → html_theme_menu
HTML_THEME_KEY = "html_theme"


async def get_html_reply_subject(session, user: User, *, fallback: str = "") -> str:
    """
    Тема для HTML при 🟢 Спуфинг: «Тема для HTML».
    Иначе — как у обычного ответа (Re: …). Рассылка — отдельно, global OFFER.
    """
    from services.html_spoof import is_spoofing_enabled

    if await is_spoofing_enabled(session, user):
        subj = sanitize_email_subject(await get_user_setting(session, user, HTML_THEME_KEY) or "")
        if subj:
            return subj[:140] if len(subj) > 140 else subj
    fb = sanitize_email_subject(fallback or "")
    return fb[:140] if len(fb) > 140 else (fb or "Message")


def account_sender_display_name(user: User) -> str | None:
    """Имя From из настроек почты (рассылка и обычные ответы, без HTML-спуфа)."""
    name = sanitize_email_subject((getattr(user, "sender_name", None) or "").strip())
    return name or None


async def get_html_sender_name(session, user: User) -> str | None:
    """
    HTML: при 🟢 Спуфинг — имя из «👤 Имя для спуфинга».
    Иначе — имя отправителя из аккаунтов (user.sender_name), как при рассылке.
    """
    spoof = await get_spoof_display_name(session, user)
    if spoof:
        return sanitize_email_subject(spoof)
    return account_sender_display_name(user)


async def prepare_html_body(html: str, session, user: User) -> str:
    nick = await get_spoof_display_name(session, user)
    return apply_nick_to_html(html, nick)


def _canon_email(email: str) -> str:
    return (email or "").strip().lower()


def _format_eur_price(price: str) -> str:
    p = (price or "").strip()
    if not p:
        return ""
    # «0» / «0 €» / «EUR 0» — для HTML считаем пустым (часто мусор после parse).
    digits = re.sub(r"[^\d.,]", "", p).replace(",", ".")
    try:
        if digits and float(digits) == 0:
            return ""
    except ValueError:
        pass
    up = p.upper()
    if "EUR" in up or "€" in p:
        # Убираем дубль вида «EUR 0 €» → нормализуем число + EUR
        m = re.search(r"([\d]+(?:[.,]\d+)?)", p)
        if m:
            num = m.group(1).replace(",", ".")
            try:
                return f"EUR {float(num):.2f}"
            except ValueError:
                return f"EUR {m.group(1)}"
        return p
    return f"EUR {p}"


def _pick_non_zero_price(*candidates: str) -> str:
    for c in candidates:
        formatted = _format_eur_price((c or "").strip())
        if formatted:
            return formatted
    return ""


async def build_offer_html_ctx(
    session,
    user_id: int,
    seller_email: str,
    *,
    link: str = "",
    offer=None,
    mail=None,
) -> dict[str, str]:
    """Контекст для HTML: лот (title/price/photo) + покупатель (поля HTML Evoleum) + ссылка."""
    from datetime import datetime

    from sqlalchemy import select

    from models import Offer, OfferEmail, User
    from services.aqua_keys import resolve_html_buyer_profile
    from services.offer_storage import (
        offer_effective_photo,
        offer_effective_price,
        offer_effective_title,
    )

    title = ""
    price = ""
    photo = ""
    off = offer
    try:
        if off is None and mail is not None:
            rid = getattr(mail, "resolved_offer_id", None)
            if rid:
                off = (
                    await session.execute(
                        select(Offer)
                        .where(Offer.id == int(rid))
                        .where(Offer.user_id == int(user_id))
                        .limit(1)
                    )
                ).scalars().first()
        if off is None:
            canon = _canon_email(seller_email)
            off = (
                await session.execute(
                    select(Offer)
                    .join(OfferEmail, OfferEmail.offer_id == Offer.id)
                    .where(Offer.user_id == int(user_id))
                    .where(OfferEmail.email == canon)
                    .order_by(Offer.id.desc())
                    .limit(1)
                )
            ).scalars().first()
        if off:
            title = (offer_effective_title(off) or "").strip()
            photo = (offer_effective_photo(off) or "").strip()
    except Exception:
        pass

    mail_price = ""
    mail_title = ""
    mail_photo = ""
    if mail is not None:
        mail_title = (getattr(mail, "product_title", None) or "").strip()
        mail_price = (getattr(mail, "offer_price", None) or "").strip()
        mail_photo = (getattr(mail, "photo_url", None) or "").strip()
        if not title:
            title = mail_title
        if not photo:
            photo = mail_photo

    offer_price_raw = ""
    try:
        if off is not None:
            offer_price_raw = (offer_effective_price(off, default="") or "").strip()
            col_price = (getattr(off, "price", None) or "").strip()
            offer_price_raw = offer_price_raw or col_price
    except Exception:
        pass

    # Сначала цена с письма/кнопки «Цена», потом оффер (0 от parse отбрасываем).
    price = _pick_non_zero_price(mail_price, offer_price_raw)

    buyer_name = ""
    address = ""
    try:
        user = await session.get(User, int(user_id))
        if user:
            buyer_name, address = await resolve_html_buyer_profile(session, user)
    except Exception:
        pass

    return {
        "ITEM_TITLE": title,
        "PRICE": price,
        "IMAGE_URL": photo,
        "SELLER_EMAIL": _canon_email(seller_email),
        "BUYER_NAME": buyer_name,
        "ADDRESS": address,
        "DATE": datetime.now().strftime("%d/%m/%Y"),
        "LINK": (link or "").strip(),
    }


async def resolve_aqua_link_for_reply(
    session,
    user_id: int,
    *,
    account_email: str,
    seller_email: str,
    mail_generated_link: str | None = None,
) -> str:
    """AQUA-ссылка из ConversationLink или из письма после «Создать ссылку»."""
    from sqlalchemy import select

    from models import ConversationLink

    link = (mail_generated_link or "").strip()
    if link:
        return link

    inbox = _canon_email(account_email)
    seller = _canon_email(seller_email)
    if inbox and seller:
        conv = (
            await session.execute(
                select(ConversationLink)
                .where(ConversationLink.user_id == int(user_id))
                .where(ConversationLink.account_email == inbox)
                .where(ConversationLink.from_email == seller)
            )
        ).scalar_one_or_none()
        if conv and conv.generated_link:
            return str(conv.generated_link).strip()
    return ""
