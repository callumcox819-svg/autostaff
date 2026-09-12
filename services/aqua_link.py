"""Генерация ссылок для оффера / входящих (CSM / Evoleum / Hustle Castle)."""

from __future__ import annotations

import logging

from sqlalchemy import func, select

from config import config
from models import Offer, User
from services.api_teams import get_selected_team_config
from services.aqua_network import AquaError
from services.csm_catalog import is_verify_service, service_key_label
from services.csm_network import CsmError, csm_generate_manual, csm_generate_parse
from services.goo_network import GooError, goo_generate_no_parse, goo_generate_parse
from services.hustle_catalog import (
    EBAY_DE_CUSTOM,
    is_hustle_custom,
    is_hustle_fast,
    is_hustle_verify,
)
from services.hustle_network import (
    HustleError,
    hustle_generate_custom,
    hustle_generate_fast,
    hustle_generate_lonely,
)
from services.offer_storage import offer_effective_photo, offer_effective_price, offer_effective_title
from utils.ui_emoji import menu_path

logger = logging.getLogger(__name__)


def _is_http_url(url: str | None) -> bool:
    u = (url or "").strip().lower()
    return u.startswith(("http://", "https://"))


async def resolve_aqua_image_url(
    session,
    user: User,
    offer: Offer | None,
    image: str | None = None,
) -> str:
    """URL фото для поля image."""
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


async def _generate_csm(session, user: User, cfg, offer: Offer | None, *, listing_url: str | None, price: str | None) -> str:
    if not (cfg.api_key or "").strip():
        raise AquaError(
            f"Не задан API-ключ для <b>{cfg.label}</b>. "
            f"{menu_path(('settings', ''), ('key', 'Команды API'))} → {cfg.label}."
        )
    if not (cfg.service_code or "").strip():
        raise AquaError(
            f"Не выбрана площадка CSM. "
            f"{menu_path(('settings', ''), ('key', 'Команды API'))} → CSM → Страна / площадка."
        )

    listing = (listing_url or "").strip()
    if not listing and offer is not None:
        listing = (getattr(offer, "link", None) or getattr(offer, "item_link", None) or "").strip()

    verify = is_verify_service(cfg.service_code)
    if not verify and not (cfg.profile_id or "").strip():
        raise AquaError(
            f"Не задан Profile ID для <b>{cfg.label}</b> "
            f"(площадка <code>{service_key_label(cfg.service_code)}</code>)."
        )

    try:
        if verify:
            seller = offer_effective_title(offer) if offer is not None else ""
            if not seller:
                raise AquaError("Для Verify нужно имя продавца / название")
            return await csm_generate_manual(
                api_key=cfg.api_key,
                service_key=cfg.service_code,
                seller_name=seller,
            )

        if _is_http_url(listing):
            return await csm_generate_parse(
                api_key=cfg.api_key,
                service_key=cfg.service_code,
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
        return await csm_generate_manual(
            api_key=cfg.api_key,
            service_key=cfg.service_code,
            product_title=title,
            product_price=p,
            image_url=image or "",
            profile_id=cfg.profile_id,
        )
    except CsmError as e:
        raise AquaError(str(e)) from e


async def _generate_goo(
    session,
    user: User,
    cfg,
    offer: Offer | None,
    *,
    listing_url: str | None,
    price: str | None,
    force_no_parse: bool = False,
) -> str:
    if not (cfg.api_key or "").strip():
        raise AquaError(
            f"Не задан API-ключ для <b>{cfg.label}</b>. "
            f"{menu_path(('settings', ''), ('key', 'Команды API'))} → {cfg.label}."
        )
    if not (cfg.team_key or "").strip():
        raise AquaError(
            "Генерация недоступна: на сервере не задан team-ключ. Напишите админу."
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

    async def _no_parse() -> str:
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

    # Кнопка «Цена» / явный force: только no-parse (parse не принимает price → часто 0 € с МП).
    if force_no_parse:
        try:
            return await _no_parse()
        except GooError as e:
            raise AquaError(str(e)) from e

    try:
        if _is_http_url(listing):
            try:
                return await goo_generate_parse(
                    user_api_key=cfg.api_key,
                    team_api_key=cfg.team_key,
                    service=cfg.service_code,
                    listing_url=listing,
                    profile_id=cfg.profile_id,
                )
            except GooError as e:
                msg = str(e).lower()
                # Парсер часто валится на битых/устаревших URL MP — как в finland-bot, уходим в no-parse.
                if "401" in msg or "403" in msg or "invalid credentials" in msg:
                    raise
                try:
                    return await _no_parse()
                except AquaError:
                    raise AquaError(str(e)) from e
        return await _no_parse()
    except GooError as e:
        raise AquaError(str(e)) from e


async def _generate_hustle(
    session,
    user: User,
    cfg,
    offer: Offer | None,
    *,
    listing_url: str | None,
    price: str | None,
) -> str:
    if not (cfg.api_key or "").strip():
        raise AquaError(
            f"Не задан API-ключ для <b>{cfg.label}</b>. "
            f"{menu_path(('settings', ''), ('key', 'Команды API'))} → {cfg.label}."
        )
    if not (cfg.team_key or "").strip():
        raise AquaError(
            "Генерация Hustle Castle недоступна: на сервере не задан "
            "<code>HUSTLE_TEAM_KEY</code>. Напишите админу."
        )
    if not (cfg.service_code or "").strip():
        raise AquaError(
            f"Не выбрана площадка Hustle Castle. "
            f"{menu_path(('settings', ''), ('key', 'Команды API'))} → Hustle Castle → Страна / площадка."
        )

    from services.api_teams import get_team_field

    buyer = (await get_team_field(session, user, "hustle", "buyer_name") or "").strip()
    address = (await get_team_field(session, user, "hustle", "address") or "").strip()
    listing = (listing_url or "").strip()
    if not listing and offer is not None:
        listing = (getattr(offer, "link", None) or getattr(offer, "item_link", None) or "").strip()
    title = offer_effective_title(offer) if offer is not None else ""
    p = (price or "").strip()
    if offer is not None:
        p = p or offer_effective_price(offer)
    image = await resolve_aqua_image_url(session, user, offer)
    link_type = (cfg.link_type or "lk").strip() or "lk"
    svc = (cfg.service_code or "").strip()

    try:
        if is_hustle_verify(svc):
            seller = title
            if not seller:
                raise AquaError("Для Verify нужно имя продавца / название")
            return await hustle_generate_lonely(
                api_key=cfg.api_key,
                team_key=cfg.team_key,
                service=svc,
                name=seller,
                price=p or "0",
                user=buyer or seller,
                address=address or "Deutschland",
                photo=image or "https://upload.wikimedia.org/wikipedia/commons/thumb/1/1b/EBay_logo.svg/256px-EBay_logo.svg.png",
                link_type=link_type,
            )

        if is_hustle_custom(svc):
            if not title:
                raise AquaError("Нет названия объявления")
            if not p:
                raise AquaError("Нет цены")
            return await hustle_generate_custom(
                api_key=cfg.api_key,
                team_key=cfg.team_key,
                name=title,
                price=p,
                user=buyer,
                address=address,
                photo=image,
                platform=EBAY_DE_CUSTOM if svc == "ebay_de" else EBAY_DE_CUSTOM,
                link_type=link_type,
            )

        if is_hustle_fast(svc) and _is_http_url(listing) and (cfg.profile_id or "").strip():
            try:
                return await hustle_generate_fast(
                    api_key=cfg.api_key,
                    team_key=cfg.team_key,
                    service=svc,
                    listing_url=listing,
                    profile_id=cfg.profile_id,
                    link_type=link_type,
                )
            except HustleError as e:
                msg = str(e).lower()
                if "401" in msg or "403" in msg:
                    raise
                logger.warning("hustle fast failed, lonely fallback: %s", e)

        if not title:
            raise AquaError("Нет названия объявления")
        if not p:
            raise AquaError("Нет цены")
        return await hustle_generate_lonely(
            api_key=cfg.api_key,
            team_key=cfg.team_key,
            service=svc,
            name=title,
            price=p,
            user=buyer,
            address=address,
            photo=image,
            link_type=link_type,
        )
    except HustleError as e:
        raise AquaError(str(e)) from e


async def aqua_generate_for_offer(
    session,
    user: User,
    offer: Offer | None,
    *,
    listing_url: str | None = None,
    price: str | None = None,
    force_no_parse: bool = False,
) -> str:
    """
    Генерация через выбранную команду:
    - CSM → meowsavings Internal API (serviceKey + Bearer)
    - Hustle Castle → INC-CORE (fast / lonely / custom)
    - Evoleum → GOO parse / no-parse
    """
    cfg = await get_selected_team_config(session, user)
    if cfg.team_id == "csm":
        return await _generate_csm(session, user, cfg, offer, listing_url=listing_url, price=price)
    if cfg.team_id == "hustle":
        return await _generate_hustle(session, user, cfg, offer, listing_url=listing_url, price=price)
    return await _generate_goo(
        session,
        user,
        cfg,
        offer,
        listing_url=listing_url,
        price=price,
        force_no_parse=force_no_parse,
    )
