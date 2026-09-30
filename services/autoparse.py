"""Авто-парс XProject → JSON бота → валидация email."""

from __future__ import annotations

from typing import Any

from services.enabled_countries import get_active_country, normalize_country_id
from services.user_settings import get_user_setting, set_user_setting
from utils.secrets import clean_secret

AUTOPARSE_KEY = "autoparse_api_key"
AUTOPARSE_COUNTRY_KEY = "autoparse_country"
AUTOPARSE_COUNT_KEY = "autoparse_json_count"
AUTOPARSE_PLATFORM_KEY = "autoparse_platform"

DEFAULT_JSON_COUNT = 100
MIN_JSON_COUNT = 10
MAX_JSON_COUNT = 500

# Площадка парсера, если у неё одна страна или она главная в боте.
_PLATFORM_BY_COUNTRY: dict[str, str] = {
    "nl": "marktplaats",
    "de": "kleinanzeigen",
    "be": "dehands",
    "ch": "ricardo",
    "fr": "leboncoin",
    "it": "subito",
    "us": "depop",
    "ca": "kijiji",
}

_VINTED_OK = frozenset(
    {
        "lt",
        "de",
        "cz",
        "at",
        "es",
        "nl",
        "se",
        "gb",
        "us",
        "pl",
        "fr",
        "it",
        "be",
        "lu",
        "pt",
        "sk",
        "hu",
        "ro",
        "dk",
        "fi",
        "hr",
        "gr",
        "ie",
        "ee",
        "lv",
        "si",
    }
)


def parser_iso_country(bot_cc: str) -> str:
    cc = (bot_cc or "").strip().lower()
    if cc == "uk":
        return "gb"
    return cc


def default_platform_for_country(bot_cc: str) -> str:
    cc = parser_iso_country(bot_cc)
    if cc in _PLATFORM_BY_COUNTRY:
        return _PLATFORM_BY_COUNTRY[cc]
    if cc in _VINTED_OK:
        return "vinted"
    return "vinted"


def listing_to_item(listing: dict[str, Any]) -> dict[str, Any]:
    title = str(listing.get("title") or "").strip()
    price = listing.get("price")
    cur = str(listing.get("currency") or "").strip()
    if price is None or price == "":
        price_s = ""
    else:
        price_s = f"{price} {cur}".strip() if cur else str(price)
    url = str(listing.get("url") or "").strip()
    image = str(listing.get("image") or "").strip()
    seller = str(listing.get("seller_name") or "").strip()
    return {
        "item_title": title,
        "title": title,
        "item_price": price_s,
        "item_link": url,
        "link": url,
        "url": url,
        "item_photo": image,
        "image": image,
        "item_person_name": seller,
        "seller_name": seller,
        "platform": str(listing.get("platform") or ""),
        "country": str(listing.get("country") or ""),
        "row_id": listing.get("row_id"),
    }


def schema_platforms(schema: dict[str, Any]) -> list[dict[str, Any]]:
    rows = schema.get("platforms") if isinstance(schema, dict) else None
    if not isinstance(rows, list):
        return []
    return [p for p in rows if isinstance(p, dict) and p.get("platform")]


def platform_schema(schema: dict[str, Any], platform: str) -> dict[str, Any] | None:
    want = (platform or "").strip().lower()
    for p in schema_platforms(schema):
        if str(p.get("platform") or "").strip().lower() == want:
            return p
    return None


def build_start_filters(
    plat: dict[str, Any] | None,
    *,
    bot_cc: str,
    json_count: int,
    infinite: bool,
) -> dict[str, Any]:
    supported = {
        str(x).strip()
        for x in ((plat or {}).get("supported_filters") or [])
        if str(x).strip()
    }
    iso = parser_iso_country(bot_cc)
    countries = [str(c).lower() for c in ((plat or {}).get("countries") or [])]
    filters: dict[str, Any] = {}
    if "internal_listing_count" in supported:
        filters["internal_listing_count"] = int(json_count)
    if "internal_view_count" in supported:
        filters["internal_view_count"] = 0
    if "seller_email" in supported:
        filters["seller_email"] = True
    if "created_at_period" in supported:
        filters["created_at_period"] = "fresh" if infinite else "7d"
    if "countries" in supported and iso in countries:
        filters["countries"] = [iso]
    return filters


def task_is_active(task: dict[str, Any] | None) -> bool:
    if not isinstance(task, dict):
        return False
    st = str(task.get("status") or "").strip().lower()
    return st not in {"stopped", "stop", "done", "finished", "error", "failed"}


def pick_existing_task(
    tasks: list[dict[str, Any]],
    *,
    platform: str,
) -> dict[str, Any] | None:
    want = (platform or "").strip().lower()
    alive = [t for t in tasks if task_is_active(t)]
    for t in alive:
        if str(t.get("platform") or "").strip().lower() == want:
            return t
    return alive[0] if alive else None


def merge_filters_keep_user(
    existing: dict[str, Any] | None,
    *,
    json_count: int,
    supported: set[str] | None = None,
) -> dict[str, Any]:
    """Фильтры с задачи XProject; меняем только размер выдачи (JSON)."""
    out: dict[str, Any] = {}
    src = existing if isinstance(existing, dict) else {}
    for k, v in src.items():
        key = str(k).strip()
        if not key:
            continue
        if v is None or v is False:
            continue
        if isinstance(v, str) and not v.strip():
            continue
        if isinstance(v, (list, tuple)) and len(v) == 0:
            continue
        out[key] = v
    if supported is None or "internal_listing_count" in supported or not supported:
        out["internal_listing_count"] = int(json_count)
    return out


def clamp_json_count(raw: str | int | None) -> int:
    try:
        n = int(str(raw or "").strip())
    except ValueError:
        return DEFAULT_JSON_COUNT
    return max(MIN_JSON_COUNT, min(MAX_JSON_COUNT, n))


async def get_autoparse_key(session, user) -> str:
    return (await get_user_setting(session, user, AUTOPARSE_KEY) or "").strip()


async def set_autoparse_key(session, user, value: str) -> None:
    await set_user_setting(session, user, AUTOPARSE_KEY, clean_secret(value))


async def get_autoparse_country(session, user) -> str:
    raw = (await get_user_setting(session, user, AUTOPARSE_COUNTRY_KEY) or "").strip().lower()
    cc = normalize_country_id(raw)
    if cc:
        return cc
    return await get_active_country(session, user)


async def set_autoparse_country(session, user, country_id: str) -> str:
    cc = normalize_country_id(country_id)
    if not cc:
        raise ValueError("unknown country")
    await set_user_setting(session, user, AUTOPARSE_COUNTRY_KEY, cc)
    plat = default_platform_for_country(cc)
    await set_user_setting(session, user, AUTOPARSE_PLATFORM_KEY, plat)
    return cc


async def get_autoparse_platform(session, user) -> str:
    raw = (await get_user_setting(session, user, AUTOPARSE_PLATFORM_KEY) or "").strip().lower()
    if raw:
        return raw
    cc = await get_autoparse_country(session, user)
    return default_platform_for_country(cc)


async def get_json_count(session, user) -> int:
    return clamp_json_count(await get_user_setting(session, user, AUTOPARSE_COUNT_KEY))


async def set_json_count(session, user, n: int) -> int:
    v = clamp_json_count(n)
    await set_user_setting(session, user, AUTOPARSE_COUNT_KEY, str(v))
    return v
