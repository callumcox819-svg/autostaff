"""Настройки, привязанные к рабочей стране (пресеты, домены, темы)."""

from __future__ import annotations

from services.csm_catalog import country_label as csm_country_label
from services.enabled_countries import get_active_country, normalize_country_id
from services.user_settings import get_user_setting, set_user_setting
from services.users import get_or_create_user

LEGACY_COUNTRY = "nl"

GERMANY_VALIDATION_DOMAINS: tuple[str, ...] = (
    "gmx.de",
    "gmail.com",
    "web.de",
    "icloud.com",
    "gmx.net",
    "outlook.de",
    "t-online.de",
    "hotmail.de",
)


def scoped_setting_key(base: str, country: str) -> str:
    cc = normalize_country_id(country) or LEGACY_COUNTRY
    return f"{base}__{cc}"


def scoped_blob_key(base: str, country: str) -> str:
    return scoped_setting_key(base, country)


def germany_generate_service(team_id: str) -> str:
    """Германия → eBay.de в формате выбранной команды (CSM / Hustle / Evoleum)."""
    return "ebay_de"


def force_germany_ebay_service(team_id: str, service_code: str) -> str:
    """Verify оставляем, остальное на Германии гоняем через ebay.de."""
    from services.csm_catalog import is_verify_service
    from services.hustle_catalog import is_hustle_verify

    tid = (team_id or "").strip().lower()
    code = (service_code or "").strip()
    if tid == "csm" and is_verify_service(code):
        return code
    if tid == "hustle" and is_hustle_verify(code):
        return code
    return germany_generate_service(tid)


def default_validation_domains_for(country: str) -> tuple[str, ...]:
    cc = normalize_country_id(country) or LEGACY_COUNTRY
    if cc == "de":
        return GERMANY_VALIDATION_DOMAINS
    from region import DEFAULT_VALIDATION_DOMAINS

    return DEFAULT_VALIDATION_DOMAINS


async def get_scoped_setting(session, user, key: str, *, country: str | None = None) -> str | None:
    cc = country or await get_active_country(session, user)
    scoped = await get_user_setting(session, user, scoped_setting_key(key, cc))
    if scoped is not None:
        return scoped
    if cc == LEGACY_COUNTRY:
        return await get_user_setting(session, user, key)
    return None


async def set_scoped_setting(session, user, key: str, value: str, *, country: str | None = None) -> None:
    cc = country or await get_active_country(session, user)
    await set_user_setting(session, user, scoped_setting_key(key, cc), value)


async def active_country_for_tg(telegram_id: int) -> str:
    from database import Session

    async with Session() as session:
        user = await get_or_create_user(session, int(telegram_id))
        return await get_active_country(session, user)


def country_display_name(country: str) -> str:
    return csm_country_label(normalize_country_id(country) or country)
