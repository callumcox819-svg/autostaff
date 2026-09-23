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


async def live_account_sender_display_name(session, user: User) -> str | None:
    from services.users import load_live_sender_name

    uid = getattr(user, "id", None)
    name = ""
    if uid:
        name = await load_live_sender_name(session, user_id=int(uid))
    if not name:
        name = (getattr(user, "sender_name", None) or "").strip()
    return sanitize_email_subject(name) or None


async def get_html_sender_name(session, user: User) -> str | None:
    """
    HTML: при 🟢 Спуфинг — имя из «👤 Имя для спуфинга».
    Иначе — имя отправителя из аккаунтов (user.sender_name), как при рассылке.
    """
    spoof = await get_spoof_display_name(session, user)
    if spoof:
        return sanitize_email_subject(spoof)
    return await live_account_sender_display_name(session, user)


async def prepare_html_body(html: str, session, user: User) -> str:
    nick = await get_spoof_display_name(session, user)
    return apply_nick_to_html(html, nick)


def _canon_email(email: str) -> str:
    from services.email_address import canonicalize_dialog_email

    return canonicalize_dialog_email(email)


def _html_currency_for_country(country: str) -> str:
    cc = (country or "").strip().lower()
    if cc == "ch":
        return "CHF"
    if cc == "hu":
        return "HUF"
    return "EUR"


def _collapse_price_thousands(price: str) -> str:
    """155 000 Ft / 155\u00a0000 → 155000 Ft."""
    s = (price or "").replace("\u00a0", " ").replace("\u202f", " ")
    while True:
        nxt = re.sub(r"(\d)[ ](\d{3})\b", r"\1\2", s)
        if nxt == s:
            return s
        s = nxt


def _format_huf_amount(num: float) -> str:
    n = int(round(float(num)))
    grouped = f"{n:,}".replace(",", " ")
    return f"{grouped} Ft"


def _detect_html_currency(price: str, fallback: str) -> str:
    raw = price or ""
    up = raw.upper()
    if "HUF" in up or re.search(r"(?i)(?:^|[^A-Z])FT(?:\b|$)", raw):
        return "HUF"
    return (fallback or "EUR").strip().upper() or "EUR"


def _format_html_price(price: str, *, currency: str = "EUR") -> str:
    p = (price or "").strip()
    if not p:
        return ""
    compact = _collapse_price_thousands(p)
    cur = _detect_html_currency(compact, currency)
    # «0» / «0 €» / «EUR 0» — для HTML считаем пустым (часто мусор после parse).
    digits = re.sub(r"[^\d.,]", "", compact).replace(",", ".")
    try:
        if digits and float(digits) == 0:
            return ""
    except ValueError:
        pass
    m = re.search(r"([\d]+(?:[.,]\d+)?)", compact)
    if not m:
        return f"{cur} {p}" if cur != "HUF" else p
    num_raw = m.group(1)
    swiss_dot = ".-" in compact[m.start() :]
    up = compact.upper()
    has_money_token = (
        any(tok in up for tok in ("EUR", "CHF", "USD", "HUF"))
        or "€" in compact
        or "FR." in up
        or bool(re.search(r"(?i)(?:^|[^A-Z])FT(?:\b|$)", compact))
    )
    if cur == "HUF":
        try:
            num = float(num_raw.replace(",", "."))
        except ValueError:
            return compact
        return _format_huf_amount(num)
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
    cur = (currency or "EUR").strip().upper() or "EUR"
    ordered = list(candidates)
    if cur == "HUF":
        preferred: list[str] = []
        rest: list[str] = []
        for c in candidates:
            raw = (c or "").strip()
            up = raw.upper()
            if "FT" in up or "HUF" in up or re.search(r"\d[ \u00a0]\d{3}", raw):
                preferred.append(raw)
            else:
                rest.append(raw)
        ordered = preferred + rest
    for c in ordered:
        formatted = _format_html_price((c or "").strip(), currency=cur)
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
    account_email: str = "",
) -> dict[str, str]:
    """Контекст для HTML: лот (title/price/photo) + покупатель (поля HTML Evoleum) + ссылка."""
    from datetime import datetime

    from sqlalchemy import func, select

    from models import Offer, OfferEmail, User
    from services.aqua_keys import resolve_html_buyer_profile
    from services.aqua_link import normalize_http_image_url, resolve_aqua_image_url
    from services.enabled_countries import get_active_country
    from services.offer_storage import (
        offer_aqua_pin,
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
            from services.email_address import dialog_email_match_keys

            seller_keys = dialog_email_match_keys(seller_email)
            if seller_keys:
                off = (
                    await session.execute(
                        select(Offer)
                        .join(OfferEmail, OfferEmail.offer_id == Offer.id)
                        .where(Offer.user_id == int(user_id))
                        .where(func.lower(OfferEmail.email).in_(seller_keys))
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
        inbox = (account_email or "").strip()
        if not inbox and mail is not None:
            inbox = (getattr(mail, "account_email", None) or "").strip()
        pin_link, pin_price, pin_offer_id = await load_dialog_html_pin(
            session, int(user_id), inbox_email=inbox, seller_email=seller_email
        )
        if off is None and pin_offer_id:
            off = (
                await session.execute(
                    select(Offer)
                    .where(Offer.id == int(pin_offer_id))
                    .where(Offer.user_id == int(user_id))
                    .limit(1)
                )
            ).scalars().first()
            if off:
                title = title or (offer_effective_title(off) or "").strip()
                photo = photo or normalize_http_image_url(offer_effective_photo(off))
                offer_price_raw = (offer_effective_price(off, default="") or "").strip() or (
                    getattr(off, "price", None) or ""
                ).strip()
        offer_link, offer_pin_price = "", ""
        if off is not None:
            offer_link, offer_pin_price = offer_aqua_pin(off)
        if not offer_link:
            offer_link, offer_pin_price, pin_off = await _latest_offer_aqua_pin_for_seller(
                session, int(user_id), seller_email
            )
            if pin_off is not None and off is None:
                off = pin_off
                title = title or (offer_effective_title(off) or "").strip()
                photo = photo or normalize_http_image_url(offer_effective_photo(off))
                offer_price_raw = (offer_effective_price(off, default="") or "").strip() or (
                    getattr(off, "price", None) or ""
                ).strip()
        mail_pin_link, mail_pin_price, mail_pin_oid = await _latest_mail_aqua_pin(
            session, int(user_id), seller_email
        )
        pin_price = offer_pin_price or pin_price or mail_pin_price
        # Только последняя сгенерированная ссылка (пин лота / свежее письмо).
        # Аргумент link / stale conv / первая parse-ссылка не имеют приоритета.
        if offer_link:
            link = offer_link
        elif mail_pin_link:
            link = mail_pin_link
        elif pin_link:
            link = pin_link
        _ = mail_pin_oid
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
    from sqlalchemy import case, func, select

    from models import ConversationLink
    from services.email_address import dialog_email_match_keys

    seller_keys = dialog_email_match_keys(seller_email)
    if not seller_keys:
        return None
    inbox_keys = dialog_email_match_keys(inbox_email)
    q = (
        select(ConversationLink)
        .where(ConversationLink.user_id == int(user_id))
        .where(func.lower(ConversationLink.from_email).in_(seller_keys))
        .order_by(
            case(
                (
                    (ConversationLink.generated_link.isnot(None))
                    & (func.length(ConversationLink.generated_link) > 0),
                    0,
                ),
                else_=1,
            ),
            ConversationLink.id.desc(),
        )
    )
    if inbox_keys:
        exact = (
            await session.execute(
                q.where(func.lower(ConversationLink.account_email).in_(inbox_keys)).limit(1)
            )
        ).scalars().first()
        if exact:
            return exact
    return (await session.execute(q.limit(1))).scalars().first()


async def _latest_offer_aqua_pin_for_seller(
    session, user_id: int, seller_email: str
) -> tuple[str, str, object | None]:
    from sqlalchemy import func, select

    from models import Offer, OfferEmail
    from services.email_address import dialog_email_match_keys
    from services.offer_storage import AQUA_PIN_LINK_KEY, offer_aqua_pin

    seller_keys = dialog_email_match_keys(seller_email)
    if seller_keys:
        rows = (
            await session.execute(
                select(Offer)
                .join(OfferEmail, OfferEmail.offer_id == Offer.id)
                .where(Offer.user_id == int(user_id))
                .where(func.lower(OfferEmail.email).in_(seller_keys))
                .order_by(Offer.id.desc())
                .limit(8)
            )
        ).scalars().all()
        for off in rows:
            ol, op = offer_aqua_pin(off)
            if ol:
                return ol, op, off
    rows = (
        await session.execute(
            select(Offer)
            .where(Offer.user_id == int(user_id))
            .where(Offer.raw_json.contains(AQUA_PIN_LINK_KEY))
            .order_by(Offer.id.desc())
            .limit(8)
        )
    ).scalars().all()
    for off in rows:
        ol, op = offer_aqua_pin(off)
        if ol:
            return ol, op, off
    return "", "", None


async def load_dialog_html_pin(
    session,
    user_id: int,
    *,
    inbox_email: str,
    seller_email: str,
) -> tuple[str, str, int | None]:
    """Последняя AQUA-ссылка и цена диалога (после «Создать ссылку» / смены цены)."""
    conv = await _get_conversation_link(session, user_id, inbox_email, seller_email)
    link = ""
    price = ""
    oid_i = None
    if conv:
        link = (getattr(conv, "generated_link", None) or "").strip()
        price = (getattr(conv, "last_generated_price", None) or "").strip()
        oid = getattr(conv, "pinned_offer_id", None)
        try:
            oid_i = int(oid) if oid else None
        except (TypeError, ValueError):
            oid_i = None
    if not link:
        mail_link, mail_price, mail_oid = await _latest_mail_aqua_pin(
            session, user_id, seller_email
        )
        link = link or mail_link
        price = price or mail_price
        oid_i = oid_i or mail_oid
    return link, price, oid_i


async def _latest_mail_aqua_pin(session, user_id: int, seller_email: str) -> tuple[str, str, int | None]:
    from sqlalchemy import func, select

    from models import IncomingMail
    from services.email_address import dialog_email_match_keys

    seller_keys = dialog_email_match_keys(seller_email)
    if not seller_keys:
        return "", "", None
    row = (
        await session.execute(
            select(IncomingMail)
            .where(IncomingMail.user_id == int(user_id))
            .where(func.lower(IncomingMail.from_email).in_(seller_keys))
            .where(IncomingMail.generated_link.isnot(None))
            .where(func.length(IncomingMail.generated_link) > 0)
            .order_by(IncomingMail.id.desc())
            .limit(1)
        )
    ).scalars().first()
    if not row:
        return "", "", None
    oid = getattr(row, "resolved_offer_id", None)
    try:
        oid_i = int(oid) if oid else None
    except (TypeError, ValueError):
        oid_i = None
    return (
        (getattr(row, "generated_link", None) or "").strip(),
        (getattr(row, "offer_price", None) or "").strip(),
        oid_i,
    )


async def resolve_aqua_link_for_reply(
    session,
    user_id: int,
    *,
    account_email: str,
    seller_email: str,
    mail_generated_link: str | None = None,
) -> str:
    """AQUA-ссылка: пин лота после смены цены, иначе диалог, иначе письмо."""
    pin_link, _, pin_oid = await load_dialog_html_pin(
        session, int(user_id), inbox_email=account_email, seller_email=seller_email
    )
    if pin_oid:
        from services.offer_storage import offer_aqua_pin, live_user_offer

        off = await live_user_offer(session, user_id=int(user_id), offer_id=int(pin_oid))
        ol, _ = offer_aqua_pin(off)
        if ol:
            return ol
    if pin_link:
        return pin_link
    return (mail_generated_link or "").strip()
