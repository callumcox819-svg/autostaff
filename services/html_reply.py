"""Тема и имя отправителя для HTML-ответов (отдельно от рассылки с OFFER)."""

from __future__ import annotations

import re

from models import User
from services.html_spoof import apply_nick_to_html, get_spoof_display_name
from services.subject_offer import sanitize_email_subject
from services.user_settings import get_user_setting

# legacy key (settings menu); Subject больше не берётся отсюда — иначе Gmail рвёт тред
HTML_THEME_KEY = "html_theme"


async def get_html_reply_subject(session, user: User, *, fallback: str = "") -> str:
    """
    Тема SMTP для HTML всегда как у обычного ответа (Re: …).

    «Тема для HTML» больше не подставляется в Subject: Gmail рвёт диалог
    даже при верном In-Reply-To. Спуфинг HTML — только From-имя и {{NICK}}.
    """
    _ = (session, user)  # signature kept for callers / tests
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


def _html_currency_for_country(country: str) -> str:
    cc = (country or "").strip().lower()
    if cc == "ch":
        return "CHF"
    return "EUR"


def _format_html_price(price: str, *, currency: str = "EUR") -> str:
    p = (price or "").strip()
    if not p:
        return ""
    cur = (currency or "EUR").strip().upper() or "EUR"
    # «0» / «0 €» / «EUR 0» — для HTML считаем пустым (часто мусор после parse).
    digits = re.sub(r"[^\d.,]", "", p).replace(",", ".")
    try:
        if digits and float(digits) == 0:
            return ""
    except ValueError:
        pass
    m = re.search(r"([\d]+(?:[.,]\d+)?)", p)
    if not m:
        return f"{cur} {p}"
    num_raw = m.group(1)
    swiss_dot = ".-" in p[m.start() :]
    up = p.upper()
    has_money_token = any(tok in up for tok in ("EUR", "CHF", "USD")) or "€" in p or "FR." in up
    if has_money_token or "," in num_raw or "." in num_raw:
        num = num_raw.replace(",", ".")
        try:
            formatted_num = f"{float(num):.2f}"
        except ValueError:
            formatted_num = num_raw
        if swiss_dot and "." not in formatted_num:
            return f"{cur} {formatted_num}.-"
        return f"{cur} {formatted_num}"
    if swiss_dot:
        return f"{cur} {num_raw}.-"
    return f"{cur} {num_raw}"


def _format_eur_price(price: str) -> str:
    return _format_html_price(price, currency="EUR")


def _pick_non_zero_price(*candidates: str, currency: str = "EUR") -> str:
    for c in candidates:
        formatted = _format_html_price((c or "").strip(), currency=currency)
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
    from services.aqua_link import normalize_http_image_url, resolve_aqua_image_url
    from services.enabled_countries import get_active_country
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
            photo = normalize_http_image_url(offer_effective_photo(off))
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
            photo = normalize_http_image_url(mail_photo)

    offer_price_raw = ""
    try:
        if off is not None:
            offer_price_raw = (offer_effective_price(off, default="") or "").strip()
            col_price = (getattr(off, "price", None) or "").strip()
            offer_price_raw = offer_price_raw or col_price
    except Exception:
        pass

    buyer_name = ""
    address = ""
    nick = ""
    currency = "EUR"
    user = None
    try:
        user = await session.get(User, int(user_id))
        if user:
            try:
                currency = _html_currency_for_country(await get_active_country(session, user))
            except Exception:
                currency = "EUR"
            buyer_name, address = await resolve_html_buyer_profile(session, user)
            spoof = await get_spoof_display_name(session, user)
            nick = (spoof or "").strip()
    except Exception:
        pass

    pin_price = ""
    try:
        inbox = (getattr(mail, "account_email", None) or "").strip() if mail is not None else ""
        pin_link, pin_price = await load_dialog_html_pin(
            session, int(user_id), inbox_email=inbox, seller_email=seller_email
        )
        if pin_link and not (link or "").strip():
            link = pin_link
    except Exception:
        pin_price = ""

    # Последняя сгенерированная цена (кнопка «Цена») важнее 0 € с parse лота.
    price = _pick_non_zero_price(pin_price, mail_price, offer_price_raw, currency=currency)

    if not photo and user is not None:
        try:
            photo = normalize_http_image_url(
                await resolve_aqua_image_url(
                    session, user, off, image=mail_photo or None
                )
            )
        except Exception:
            pass

    return {
        "ITEM_TITLE": title,
        "PRICE": price,
        "IMAGE_URL": photo,
        "SELLER_EMAIL": _canon_email(seller_email),
        "BUYER_NAME": buyer_name,
        "NICK": nick,
        "ADDRESS": address,
        "DATE": datetime.now().strftime("%d/%m/%Y"),
        "LINK": (link or "").strip(),
    }


async def _get_conversation_link(session, user_id: int, inbox_email: str, seller_email: str):
    from sqlalchemy import func, select

    from models import ConversationLink

    inbox = _canon_email(inbox_email)
    seller = _canon_email(seller_email)
    if not inbox or not seller:
        return None
    return (
        await session.execute(
            select(ConversationLink)
            .where(ConversationLink.user_id == int(user_id))
            .where(func.lower(ConversationLink.account_email) == inbox)
            .where(func.lower(ConversationLink.from_email) == seller)
            .order_by(ConversationLink.id.desc())
            .limit(1)
        )
    ).scalars().first()


async def load_dialog_html_pin(
    session,
    user_id: int,
    *,
    inbox_email: str,
    seller_email: str,
) -> tuple[str, str]:
    """Последняя AQUA-ссылка и цена диалога (после «Создать ссылку» / смены цены)."""
    conv = await _get_conversation_link(session, user_id, inbox_email, seller_email)
    if not conv:
        return "", ""
    link = (getattr(conv, "generated_link", None) or "").strip()
    price = (getattr(conv, "last_generated_price", None) or "").strip()
    return link, price


async def resolve_aqua_link_for_reply(
    session,
    user_id: int,
    *,
    account_email: str,
    seller_email: str,
    mail_generated_link: str | None = None,
) -> str:
    """AQUA-ссылка: сначала последняя на диалоге, иначе с конкретного письма."""
    pin_link, _ = await load_dialog_html_pin(
        session, int(user_id), inbox_email=account_email, seller_email=seller_email
    )
    if pin_link:
        return pin_link
    return (mail_generated_link or "").strip()
