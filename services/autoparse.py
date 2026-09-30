"""Авто-парс XProject → JSON бота → валидация email."""

from __future__ import annotations

import json
from typing import Any

from services.enabled_countries import get_active_country, normalize_country_id
from services.user_settings import get_user_setting, set_user_setting
from utils.secrets import clean_secret

AUTOPARSE_KEY = "autoparse_api_key"
AUTOPARSE_COUNTRY_KEY = "autoparse_country"
AUTOPARSE_COUNT_KEY = "autoparse_json_count"
AUTOPARSE_PLATFORM_KEY = "autoparse_platform"
AUTOPARSE_FILTERS_PREFIX = "autoparse_filters:"

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


def supported_filter_keys(plat: dict[str, Any] | None) -> set[str]:
    return {
        str(x).strip()
        for x in ((plat or {}).get("supported_filters") or [])
        if str(x).strip()
    }


def clip_filters_to_supported(
    filters: dict[str, Any] | None,
    supported: set[str] | None,
) -> dict[str, Any]:
    src = filters if isinstance(filters, dict) else {}
    if not supported:
        return dict(src)
    return {k: v for k, v in src.items() if str(k) in supported}


def filters_storage_key(platform: str) -> str:
    plat = (platform or "").strip().lower() or "unknown"
    return f"{AUTOPARSE_FILTERS_PREFIX}{plat}"


def parse_saved_filters(raw: str | None) -> dict[str, Any]:
    s = (raw or "").strip()
    if not s:
        return {}
    try:
        data = json.loads(s)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


async def get_saved_filters(session, user, platform: str) -> dict[str, Any]:
    return parse_saved_filters(await get_user_setting(session, user, filters_storage_key(platform)))


async def set_saved_filters(session, user, platform: str, filters: dict[str, Any] | None) -> None:
    key = filters_storage_key(platform)
    src = filters if isinstance(filters, dict) else {}
    clean = {k: v for k, v in src.items() if str(k).strip()}
    await set_user_setting(session, user, key, json.dumps(clean, ensure_ascii=False))


def summarize_filters(filters: dict[str, Any] | None) -> str:
    src = filters if isinstance(filters, dict) else {}
    if not src:
        return "не заданы"
    bits: list[str] = []
    if src.get("seller_email") is True:
        bits.append("почта")
    if src.get("delivery") is True:
        bits.append("доставка")
    if src.get("seller_online") is True:
        bits.append("онлайн")
    period = src.get("created_at_period")
    if period:
        bits.append(f"дата {period}")
    if src.get("price_min") is not None:
        bits.append(f"от {src.get('price_min')}")
    if src.get("price_max") is not None:
        bits.append(f"до {src.get('price_max')}")
    sw = src.get("stop_words")
    if isinstance(sw, list) and sw:
        bits.append(f"банворды {len(sw)}")
    cats = src.get("categories")
    if isinstance(cats, list) and cats:
        labels = [category_label(x) for x in cats[:3]]
        extra = f"+{len(cats) - 3}" if len(cats) > 3 else ""
        bits.append("кат. " + ", ".join(labels) + extra)
    if src.get("internal_view_count") == 0:
        bits.append("не виденные")
    return ", ".join(bits) if bits else "сохранены"


_EVERYWHERE_SLUGS = {
    "everywhere",
    "see_everywhere",
    "look_everywhere",
    "watch_everywhere",
    "all",
    "any",
    "all_categories",
    "see_all",
}


_CATEGORY_RU: dict[str, str] = {
    "antiques_art": "Антиквариат и искусство",
    "antiques_arts": "Антиквариат и искусство",
    "audio_tv_photo": "Аудио, ТВ и фото",
    "cars": "Автомобили",
    "auto_parts": "Автозапчасти",
    "auto_misc": "Авто разное",
    "books": "Книги",
    "caravans_camping": "Караваны и кемпинг",
    "cd_dvd": "CD и DVD",
    "computers_software": "Компьютеры и софт",
    "contacts_messages": "Контакты и сообщения",
    "services": "Услуги и специалисты",
    "pets": "Животные и аксессуары",
    "diy": "DIY и ремонт",
    "bikes": "Велосипеды и мопеды",
    "hobby": "Хобби и досуг",
    "home_interior": "Дом и интерьер",
    "houses_rooms": "Дома и комнаты",
    "kids": "Дети и малыши",
    "women": "Женская одежда",
    "men": "Мужская одежда",
}


def category_label(value: Any) -> str:
    slug = str(value or "").strip()
    if not slug:
        return "?"
    low = slug.lower()
    if low in _EVERYWHERE_SLUGS or "везде" in low or "everywhere" in low:
        return "Смотреть везде"
    if low in _CATEGORY_RU:
        return _CATEGORY_RU[low]
    return slug.replace("_", " ")


def schema_category_values(plat: dict[str, Any] | None) -> list[str]:
    out: list[str] = []
    for raw in ((plat or {}).get("categories") or []):
        if isinstance(raw, str) and raw.strip():
            out.append(raw.strip())
            continue
        if isinstance(raw, dict):
            val = raw.get("value") or raw.get("id") or raw.get("key") or raw.get("slug") or raw.get("name")
            if val is not None and str(val).strip():
                out.append(str(val).strip())
    return out


def toggle_category_list(current: Any, slug: str, *, all_values: list[str] | None = None) -> list[str]:
    want = str(slug).strip()
    cur = [str(x).strip() for x in (current or []) if str(x).strip()]
    if want in cur:
        cur = [x for x in cur if x != want]
    else:
        cur.append(want)
    if all_values:
        order = {v: i for i, v in enumerate(all_values)}
        cur.sort(key=lambda x: order.get(x, 10_000))
    return cur


def pick_task_for_filters(
    tasks: list[dict[str, Any]],
    *,
    platform: str,
) -> dict[str, Any] | None:
    """Только та же площадка: сначала живая задача, иначе последняя с фильтрами."""
    want = (platform or "").strip().lower()
    same = [
        t
        for t in tasks
        if isinstance(t, dict) and str(t.get("platform") or "").strip().lower() == want
    ]
    if not same:
        return None
    for t in same:
        if task_is_active(t) and isinstance(t.get("filters"), dict):
            return t
    for t in same:
        if task_is_active(t):
            return t
    for t in same:
        if isinstance(t.get("filters"), dict) and t.get("filters"):
            return t
    return same[0]


def resolve_local_start_filters(
    *,
    plat: dict[str, Any] | None,
    bot_cc: str,
    json_count: int,
    infinite: bool,
    saved: dict[str, Any] | None,
    xp_task: dict[str, Any] | None,
) -> tuple[dict[str, Any], str]:
    supported = supported_filter_keys(plat)
    if xp_task and isinstance(xp_task.get("filters"), dict) and xp_task.get("filters"):
        merged = merge_filters_keep_user(
            xp_task.get("filters"),
            json_count=json_count,
            supported=supported,
        )
        merged = clip_filters_to_supported(merged, supported)
        tid = xp_task.get("task_id")
        return merged, f"XProject задача #{tid}"
    if saved:
        merged = merge_filters_keep_user(saved, json_count=json_count, supported=supported)
        merged = clip_filters_to_supported(merged, supported)
        iso = parser_iso_country(bot_cc)
        countries = [str(c).lower() for c in ((plat or {}).get("countries") or [])]
        if "countries" in supported and iso in countries and "countries" not in merged:
            merged["countries"] = [iso]
        return merged, "сохранённые фильтры"
    built = clip_filters_to_supported(
        build_start_filters(plat, bot_cc=bot_cc, json_count=json_count, infinite=infinite),
        supported,
    )
    return built, "дефолт"


def build_start_filters(
    plat: dict[str, Any] | None,
    *,
    bot_cc: str,
    json_count: int,
    infinite: bool,
) -> dict[str, Any]:
    supported = supported_filter_keys(plat)
    iso = parser_iso_country(bot_cc)
    countries = [str(c).lower() for c in ((plat or {}).get("countries") or [])]
    filters: dict[str, Any] = {}
    if "internal_listing_count" in supported:
        filters["internal_listing_count"] = int(json_count)
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
    return None


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
