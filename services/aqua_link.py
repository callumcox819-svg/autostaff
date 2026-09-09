"""Генерация ссылок для оффера / входящих."""

from __future__ import annotations

from sqlalchemy import func, select

from config import config
from models import Offer, User
from services.aqua_keys import (
    aqua_service_for_api,
    get_user_aqua_api_keys_async,
    get_user_aqua_service,
    get_user_profile_address,
    get_user_profile_buyer_name,
    is_valid_aqua_service,
    user_profile_fields_complete,
)
from services.aqua_network import AquaError, generate_aqua_link
from services.gag_domains import finalize_gag_generated_url, get_user_gag_domain_mode, gag_api_domain_for_mode
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
    """URL фото для поля photo в APEX API (опционально, но желательно)."""
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
    user_key, team_key = await get_user_aqua_api_keys_async(session, user)
    if not user_key:
        raise AquaError(f"Не задан личный API key. {menu_path(('settings', ''), ('key', 'Ключ'))}")
    from services.aqua_network import generate_api_configured

    if not generate_api_configured():
        raise AquaError(
            "Домен генерации не задан на сервере (GENERATE_API_BASE / GAG_API_BASE)."
        )

    if not await user_profile_fields_complete(session, user):
        raise AquaError(
            f"Профиль не заполнен. {menu_path(('settings', ''), ('profile', 'Профиль'))} → "
            "Заполнить / изменить (название, имя получателя, адрес)."
        )

    buyer_name = await get_user_profile_buyer_name(session, user)
    address = await get_user_profile_address(session, user)

    service = await get_user_aqua_service(session, user)
    if not is_valid_aqua_service(service):
        raise AquaError("Не задан сервис площадки (ricardo / tutti).")

    title = offer_effective_title(offer)
    if not title:
        raise AquaError("Нет названия объявления")

    p = (price or "").strip() or offer_effective_price(offer)
    if not p:
        raise AquaError("Нет цены")

    image = await resolve_aqua_image_url(session, user, offer)
    api_service = aqua_service_for_api(service)
    mode = await get_user_gag_domain_mode(session, user)
    api_domain = gag_api_domain_for_mode(mode)

    raw_link = await generate_aqua_link(
        user_api_key=user_key,
        team_api_key=team_key,
        service=api_service,
        buyer_name=buyer_name,
        address=address,
        listing_url=listing_url,
        name=title,
        price=p,
        image=image or None,
        domain=api_domain,
    )
    try:
        return finalize_gag_generated_url(raw_link, mode=mode)
    except ValueError as e:
        raise AquaError(str(e)) from e
