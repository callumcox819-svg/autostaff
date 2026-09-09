"""Генерация ссылок для оффера / входящих (GOO.NETWORK / выбранная команда API)."""

from __future__ import annotations

from sqlalchemy import func, select

from config import config
from models import Offer, User
from services.api_teams import get_selected_team_config
from services.aqua_network import AquaError
from services.goo_network import GooError, goo_generate_no_parse, goo_generate_parse
from utils.ui_emoji import menu_path
from services.offer_storage import offer_effective_photo, offer_effective_price, offer_effective_title


def _is_http_url(url: str | None) -> bool:
    u = (url or "").strip().lower()
    return u.startswith(("http://", "https://"))


async def resolve_aqua_image_url(
    session,
    user: User,
    offer: Offer | None,
    image: str | None = None,
) -> str:
    """URL фото для поля image в GOO no-parse."""
    for candidate in (
        (image or "").strip(),
        offer_effective_photo(offer),
    ):
        if _is_http_url(candidate):
            return candidate.strip()

    uid = int(getattr(user, "id", 0) or 0)
    if uid:
        rows = (
            await session.execute(
                select(Offer.photo)
                .where(Offer.user_id == uid, Offer.photo.is_not(None))
                .order_by(func.random())
                .limit(40)
            )
        ).scalars().all()
        for p in rows:
            ps = (p or "").strip()
            if _is_http_url(ps):
                return ps

    default = (getattr(config, "AQUA_DEFAULT_IMAGE_URL", None) or "").strip()
    if _is_http_url(default):
        return default

    return ""


async def aqua_generate_for_offer(
    session,
    user: User,
    offer: Offer | None,
    *,
    listing_url: str | None = None,
    price: str | None = None,
) -> str:
    """
    Генерация через GOO:
    - с URL объявления → /api/generate/single/parse
    - иначе → /api/generate/single/no-parse (title/price/image)
    Ключи и Profile ID — из выбранной команды (⚙️ → Команды API).
    """
    cfg = await get_selected_team_config(session, user)
    if not (cfg.api_key or "").strip():
        raise AquaError(
            f"Не задан API-ключ для <b>{cfg.label}</b>. "
            f"{menu_path(('settings', ''), ('key', 'Команды API'))} → {cfg.label}."
        )
    if not (cfg.team_key or "").strip():
        raise AquaError(
            "Не задан Team-ключ на сервере "
            "(Railway Variables: <code>GOO_TEAM_KEY</code> / <code>TEAM_API_KEY</code>)."
        )
    if not (cfg.profile_id or "").strip():
        raise AquaError(
            f"Не задан Profile ID для <b>{cfg.label}</b>. "
            f"{menu_path(('settings', ''), ('key', 'Команды API'))} → {cfg.label}."
        )
    if not (cfg.service_code or "").strip():
        raise AquaError(
            f"Не задан код сервиса для <b>{cfg.label}</b> "
            f"(для NL: <code>marktplaats_nl</code>)."
        )

    listing = (listing_url or "").strip()
    if not listing and offer is not None:
        listing = (getattr(offer, "link", None) or getattr(offer, "item_link", None) or "").strip()

    try:
        if _is_http_url(listing):
            return await goo_generate_parse(
                user_api_key=cfg.api_key,
                team_api_key=cfg.team_key,
                service=cfg.service_code,
                listing_url=listing,
                profile_id=cfg.profile_id,
            )

        title = offer_effective_title(offer)
        if not title:
            raise AquaError("Нет названия объявления")
        p = (price or "").strip() or offer_effective_price(offer)
        if not p:
            raise AquaError("Нет цены")
        image = await resolve_aqua_image_url(session, user, offer)
        return await goo_generate_no_parse(
            user_api_key=cfg.api_key,
            team_api_key=cfg.team_key,
            service=cfg.service_code,
            name=title,
            price=p,
            profile_id=cfg.profile_id,
            image=image or None,
        )
    except GooError as e:
        raise AquaError(str(e)) from e
