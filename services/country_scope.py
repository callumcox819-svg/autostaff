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
    """Дефолт генерации для Германии, если площадка в команде не задана."""
    tid = (team_id or "").strip().lower()
    if tid == "hustle":
        from services.hustle_catalog import HUSTLE_DEFAULT_SERVICE

        return HUSTLE_DEFAULT_SERVICE  # kleinanzeigen_de (FAST)
    return "ebay_de"


def austria_html_service(team_id: str = "") -> str:
    """Дефолт Австрии, если площадка без своей HTML-папки."""
    return "willhaben_at"


def austria_html_service_for_code(service_code: str) -> str:
    """Willhaben → willhaben_at, Laendleanzeiger → laendleanzeiger_at."""
    from services.csm_catalog import parse_service_key

    code = (service_code or "").strip().lower()
    if not code:
        return austria_html_service()
    if code in {"willhaben_at", "laendleanzeiger_at"}:
        return code
    platform, _cc = parse_service_key(code)
    if platform == "laendleanzeiger" or code.startswith("laendleanzeiger"):
        return "laendleanzeiger_at"
    if platform == "willhaben" or code.startswith("willhaben"):
        return "willhaben_at"
    return austria_html_service()


def force_germany_ebay_service(team_id: str, service_code: str) -> str:
    """CSM/Evoleum на DE → ebay.de; Hustle — площадка из Команды API (не ломаем FAST)."""
    from services.csm_catalog import is_verify_service
    from services.hustle_catalog import is_hustle_verify

    tid = (team_id or "").strip().lower()
    code = (service_code or "").strip()
    if tid == "hustle":
        # kleinanzeigen_de / vinted / … как выбрано; иначе дефолт FAST Kleinanzeigen
        if is_hustle_verify(code):
            return code
        return code or germany_generate_service(tid)
    if tid == "csm" and is_verify_service(code):
        return code
    return germany_generate_service(tid)


def force_austria_html_service(team_id: str, service_code: str) -> str:
    """Verify оставляем; HTML AT по выбранной площадке (willhaben / laendleanzeiger)."""
    from services.csm_catalog import is_verify_service
    from services.hustle_catalog import is_hustle_verify

    tid = (team_id or "").strip().lower()
    code = (service_code or "").strip()
    if tid == "csm" and is_verify_service(code):
        return code
    if tid == "hustle" and is_hustle_verify(code):
        return code
    return austria_html_service_for_code(code)


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
