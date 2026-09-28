"""Включённые страны пользователя (каталог CSM). Пустое значение = все включены."""

from __future__ import annotations

import json

from services.csm_catalog import CSM_COUNTRIES, list_csm_countries
from services.user_settings import get_user_setting, set_user_setting

ENABLED_COUNTRIES_KEY = "enabled_countries"
ACTIVE_COUNTRY_KEY = "active_country"
DEFAULT_ACTIVE_COUNTRY = "nl"

_ALL_IDS = tuple(cid for cid, _, _ in CSM_COUNTRIES)
_ALL_SET = frozenset(_ALL_IDS)


def normalize_country_id(raw: str | None) -> str | None:
    cc = (raw or "").strip().lower()
    if cc in _ALL_SET:
        return cc
    return None


def all_country_ids() -> tuple[str, ...]:
    return _ALL_IDS


def countries_for_settings_ui() -> list[tuple[str, str, str]]:
    """Германия и Нидерланды сверху, остальные как в CSM."""
    priority = {"de": 0, "nl": 1, "pt": 2, "hu": 3, "hr": 4}
    rows = list(CSM_COUNTRIES)
    rows.sort(key=lambda row: (priority.get(row[0], 50), row[1]))
    return rows


def parse_enabled_ids(raw: str | None) -> set[str]:
    if not (raw or "").strip():
        return set(_ALL_IDS)
    try:
        data = json.loads(raw)
    except Exception:
        return set(_ALL_IDS)
    if not isinstance(data, list) or not data:
        return set(_ALL_IDS)
    out = {str(x).strip().lower() for x in data if str(x).strip()}
    out &= _ALL_SET
    return out or set(_ALL_IDS)


async def get_enabled_country_ids(session, user) -> set[str]:
    raw = await get_user_setting(session, user, ENABLED_COUNTRIES_KEY)
    return parse_enabled_ids(raw)


def is_country_enabled(enabled: set[str], country_id: str) -> bool:
    cc = (country_id or "").strip().lower()
    if not cc or cc == "verify_all":
        return True
    if not enabled:
        return True
    return cc in enabled


def filter_csm_countries(enabled: set[str] | None) -> list[tuple[str, str, str]]:
    rows = list_csm_countries()
    if not enabled or enabled >= _ALL_SET:
        return rows
    filtered = [row for row in rows if row[0] in enabled]
    return filtered or rows


async def set_country_enabled(session, user, country_id: str, on: bool) -> set[str]:
    cid = (country_id or "").strip().lower()
    if cid not in _ALL_SET:
        raise ValueError(f"Unknown country: {country_id!r}")
    current = await get_enabled_country_ids(session, user)
    nxt = set(current)
    if on:
        nxt.add(cid)
    else:
        if cid in nxt and len(nxt) <= 1:
            raise ValueError("Нужна хотя бы одна страна")
        nxt.discard(cid)
    await set_user_setting(session, user, ENABLED_COUNTRIES_KEY, json.dumps(sorted(nxt)))
    active = await get_active_country(session, user)
    if active not in nxt:
        fallback = DEFAULT_ACTIVE_COUNTRY if DEFAULT_ACTIVE_COUNTRY in nxt else sorted(nxt)[0]
        await set_user_setting(session, user, ACTIVE_COUNTRY_KEY, fallback)
    return nxt


async def get_active_country(session, user) -> str:
    raw = await get_user_setting(session, user, ACTIVE_COUNTRY_KEY)
    cc = normalize_country_id(raw) or DEFAULT_ACTIVE_COUNTRY
    enabled = await get_enabled_country_ids(session, user)
    if cc not in enabled:
        if DEFAULT_ACTIVE_COUNTRY in enabled:
            return DEFAULT_ACTIVE_COUNTRY
        return sorted(enabled)[0] if enabled else DEFAULT_ACTIVE_COUNTRY
    return cc


async def set_active_country(session, user, country_id: str) -> str:
    cid = normalize_country_id(country_id)
    if not cid:
        raise ValueError(f"Unknown country: {country_id!r}")
    enabled = await get_enabled_country_ids(session, user)
    if cid not in enabled:
        enabled = await set_country_enabled(session, user, cid, True)
    await set_user_setting(session, user, ACTIVE_COUNTRY_KEY, cid)
    return cid
