"""Генерация ссылок для оффера / входящих (CSM / Evoleum / Hustle / BASTARD / GAG)."""

from __future__ import annotations

import logging

from sqlalchemy import func, select

from config import config
from models import Offer, User
from services.api_teams import get_selected_team_config
from services.aqua_network import AquaError, generate_aqua_link_no_parse
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


def _price_is_zero(price: str | None) -> bool:
    raw = (price or "").strip()
    if not raw:
        return True
    import re

    digits = re.sub(r"[^\d.,]", "", raw).replace(",", ".")
    try:
        return bool(digits) and float(digits) == 0.0
    except ValueError:
        return False


def _csm_product_price(*vals: str | None) -> str:
    """Первая ненулевая цена → число для Meow (250€ / 250 → 250)."""
    import re

    for raw in vals:
        s = str(raw or "").strip()
        if not s or _price_is_zero(s):
            continue
        digits = re.sub(r"[^\d.,]", "", s).replace(",", ".")
        if digits.count(".") > 1:
            digits = digits.replace(".", "", digits.count(".") - 1)
        try:
            n = float(digits)
        except ValueError:
            continue
        if n <= 0:
            continue
        if abs(n - round(n)) < 1e-9:
            return str(int(round(n)))
        return f"{n:.2f}".rstrip("0").rstrip(".")
    return ""


def normalize_http_image_url(url: str | None) -> str:
    """Абсолютный http(s) URL фото; `//cdn…` → https."""
    u = (url or "").strip()
    if not u:
        return ""
    if u.startswith("//"):
        u = "https:" + u
    if not _is_http_url(u):
        return ""
    return u


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
        norm = normalize_http_image_url(candidate)
        if norm:
            return norm

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
            norm = normalize_http_image_url(p)
            if norm:
                return norm

    default = (getattr(config, "AQUA_DEFAULT_IMAGE_URL", None) or "").strip()
    return normalize_http_image_url(default)


async def _generate_csm(
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

        from services.offer_storage import offer_effective_price, parse_offer_raw

        raw = parse_offer_raw(getattr(offer, "raw_json", None)) if offer is not None else {}
        p = _csm_product_price(
            price,
            str(raw.get("item_price") or "") if isinstance(raw, dict) else "",
            str(raw.get("price") or "") if isinstance(raw, dict) else "",
            getattr(offer, "price", None) if offer is not None else "",
            offer_effective_price(offer, default="") if offer is not None else "",
        )
        # Parse только если цены нет: иначе Meow с marktplaats-URL на olx_pt рисует 0.00€.
        use_parse = (
            not force_no_parse
            and _is_http_url(listing)
            and not p
        )
        if use_parse:
            return await csm_generate_parse(
                api_key=cfg.api_key,
                service_key=cfg.service_code,
                listing_url=listing,
                profile_id=cfg.profile_id,
            )

        title = offer_effective_title(offer)
        if not title:
            raise AquaError("Нет названия объявления")
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

    # Кнопка «Цена» / явная ненулевая цена: no-parse (parse берёт 0 € с МП).
    explicit = (price or "").strip()
    if force_no_parse or (explicit and not _price_is_zero(explicit)):
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
    team_id = (cfg.team_id or "hustle").strip().lower()
    env_key = "BASTARD_TEAM_KEY" if team_id == "bastard" else "HUSTLE_TEAM_KEY"
    if not (cfg.team_key or "").strip():
        raise AquaError(
            f"Генерация {cfg.label} недоступна: на сервере не задан "
            f"<code>{env_key}</code>. Напишите админу."
        )
    if not (cfg.service_code or "").strip():
        raise AquaError(
            f"Не выбрана площадка {cfg.label}. "
            f"{menu_path(('settings', ''), ('key', 'Команды API'))} → {cfg.label} → Страна / площадка."
        )

    from services.api_teams import get_team_field
    from services.bastard_catalog import (
        is_bastard_custom,
        is_bastard_fast,
        is_bastard_verify,
    )

    buyer = (await get_team_field(session, user, team_id, "buyer_name") or "").strip()
    address = (await get_team_field(session, user, team_id, "address") or "").strip()
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

    if team_id == "bastard":
        verify = is_bastard_verify(svc)
        custom = is_bastard_custom(svc)
        fast = is_bastard_fast(svc)
        default_addr = "Budapest"
    else:
        verify = is_hustle_verify(svc)
        custom = is_hustle_custom(svc)
        fast = is_hustle_fast(svc)
        default_addr = "Deutschland"

    try:
        if verify:
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
                address=address or default_addr,
                photo=image or "https://upload.wikimedia.org/wikipedia/commons/thumb/1/1b/EBay_logo.svg/256px-EBay_logo.svg.png",
                link_type=link_type,
            )

        if custom:
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

        # Jófogás / Kleinanzeigen — FAST: цена не должна уводить в lonely
        # (lonely на FAST-сервисе даёт Cloudflare 520 / таймаут).
        if fast:
            if not _is_http_url(listing):
                raise AquaError(
                    f"Для {cfg.label} ({svc}) нужна ссылка на объявление (item_link)."
                )
            if not (cfg.profile_id or "").strip():
                raise AquaError(
                    f"Не задан Profile ID для <b>{cfg.label}</b>. "
                    f"{menu_path(('settings', ''), ('key', 'Команды API'))} → {cfg.label}."
                )
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


async def _generate_gag(
    session,
    user: User,
    cfg,
    offer: Offer | None,
    *,
    listing_url: str | None,
    price: str | None,
) -> str:
    """GAG: POST {GENERATE_API_BASE}/generate — личный apikey, без team-ключа."""
    from services.api_teams import get_team_field
    from services.aqua_keys import get_user_profile_address, get_user_profile_buyer_name
    from services.aqua_network import generate_api_configured
    from services.gag_catalog import gag_generate_service
    from services.gag_domains import finalize_gag_generated_url, get_user_gag_domain_mode
    from services.gag_domains import gag_api_domain_for_mode

    _ = listing_url
    if not generate_api_configured():
        raise AquaError(
            "Сервис генерации GAG временно не настроен. Обратитесь к администратору."
        )
    if not (cfg.api_key or "").strip():
        raise AquaError(
            f"Не задан API-ключ для <b>{cfg.label}</b>. "
            f"{menu_path(('settings', ''), ('key', 'Команды API'))} → {cfg.label}."
        )
    svc = gag_generate_service(cfg.service_code)
    if not svc:
        raise AquaError(
            f"Не задан код сервиса GAG. "
            f"{menu_path(('settings', ''), ('key', 'Команды API'))} → GAG → Код сервиса."
        )

    buyer = (await get_team_field(session, user, "gag", "buyer_name") or "").strip()
    address = (await get_team_field(session, user, "gag", "address") or "").strip()
    if not buyer:
        buyer = (await get_user_profile_buyer_name(session, user) or "").strip()
    if not address:
        address = (await get_user_profile_address(session, user) or "").strip()
    if not buyer or not address:
        raise AquaError(
            f"Для GAG нужны ФИО и адрес. "
            f"{menu_path(('settings', ''), ('key', 'Команды API'))} → GAG."
        )

    title = offer_effective_title(offer) if offer is not None else ""
    if not title:
        raise AquaError("Нет названия объявления")
    p = (price or "").strip()
    if offer is not None:
        p = p or offer_effective_price(offer)
    if not p:
        raise AquaError("Нет цены")
    image = await resolve_aqua_image_url(session, user, offer)
    mode = await get_user_gag_domain_mode(session, user)
    domain = gag_api_domain_for_mode(mode)
    version = (cfg.link_type or "lk").strip() or "lk"

    try:
        url = await generate_aqua_link_no_parse(
            user_api_key=cfg.api_key,
            service=svc,
            name=title,
            price=p,
            buyer_name=buyer,
            address=address,
            image=image or None,
            domain=domain,
            version=version,
        )
        return finalize_gag_generated_url(url, mode=mode)
    except ValueError as e:
        raise AquaError(str(e)) from e
    except AquaError:
        raise


async def _generate_rpc(
    session,
    user: User,
    cfg,
    offer: Offer | None,
    *,
    listing_url: str | None,
    price: str | None,
) -> str:
    _ = listing_url
    from services.api_teams import get_team_field
    from services.rpc_catalog import parse_rpc_service, rpc_api_service_code
    from services.rpc_network import RpcError, rpc_create_ad, rpc_env_api_base

    if not (cfg.api_key or "").strip():
        raise AquaError(
            f"Не задан API-ключ для <b>{cfg.label}</b> (заголовок X-API-KEY). "
            f"{menu_path(('settings', ''), ('key', 'Команды API'))} → {cfg.label}."
        )
    api_base = rpc_env_api_base()
    if not api_base:
        raise AquaError(
            "Генерация RPC недоступна: на сервере не задан <code>RPC_API_BASE</code>. "
            "Напишите админу."
        )
    svc = rpc_api_service_code(cfg.service_code)
    if not svc:
        raise AquaError(
            f"Не выбрана площадка {cfg.label}. "
            f"{menu_path(('settings', ''), ('key', 'Команды API'))} → {cfg.label} → Страна / площадка."
        )
    _, country = parse_rpc_service(cfg.service_code)
    buyer = (await get_team_field(session, user, "rpc", "buyer_name") or "").strip()
    address = (await get_team_field(session, user, "rpc", "address") or "").strip()
    title = offer_effective_title(offer) if offer is not None else ""
    p = (price or "").strip()
    if offer is not None:
        p = p or offer_effective_price(offer)
    image = await resolve_aqua_image_url(session, user, offer)
    try:
        return await rpc_create_ad(
            api_key=cfg.api_key,
            api_base=api_base,
            country_code=country,
            service_code=svc,
            title=title,
            price=p,
            full_name=buyer,
            address=address,
            image=image or None,
            link_type=cfg.link_type or "lk",
        )
    except RpcError as e:
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
    - CSM → meowsavings Internal API
    - Hustle Castle → INC-CORE (fast / lonely / custom)
    - BASTARD → INC-CORE Jófogás
    - RPC → Continental Group POST /api/v1/ad/create
    - GAG → POST /generate (GENERATE_API_BASE)
    - Evoleum → GOO parse / no-parse
    """
    cfg = await get_selected_team_config(session, user)
    from dataclasses import replace

    from services.country_scope import (
        force_germany_ebay_service,
        force_hungary_jofogas_service,
        force_portugal_olx_service,
    )
    from services.enabled_countries import get_active_country

    cc = await get_active_country(session, user)
    if cfg.team_id == "gag":
        from services.gag_catalog import gag_generate_service

        if cc != "ch":
            raise AquaError("GAG доступен только для Швейцарии (Ricardo / Markt.ch).")
        cfg = replace(cfg, service_code=gag_generate_service(cfg.service_code))
    if cfg.team_id == "rpc" and cc != "hu":
        raise AquaError("RPC в боте сейчас для Венгрии. Поставь рабочую страну <b>Венгрия</b>.")
    if cc == "de":
        cfg = replace(cfg, service_code=force_germany_ebay_service(cfg.team_id, cfg.service_code))
    if cc == "pt":
        cfg = replace(cfg, service_code=force_portugal_olx_service(cfg.team_id, cfg.service_code))
    if cc == "hu":
        cfg = replace(cfg, service_code=force_hungary_jofogas_service(cfg.team_id, cfg.service_code))
    if cfg.team_id == "csm":
        return await _generate_csm(
            session,
            user,
            cfg,
            offer,
            listing_url=listing_url,
            price=price,
            force_no_parse=force_no_parse,
        )
    if cfg.team_id in {"hustle", "bastard"}:
        return await _generate_hustle(session, user, cfg, offer, listing_url=listing_url, price=price)
    if cfg.team_id == "rpc":
        return await _generate_rpc(session, user, cfg, offer, listing_url=listing_url, price=price)
    if cfg.team_id == "gag":
        return await _generate_gag(session, user, cfg, offer, listing_url=listing_url, price=price)
    return await _generate_goo(
        session,
        user,
        cfg,
        offer,
        listing_url=listing_url,
        price=price,
        force_no_parse=force_no_parse,
    )
