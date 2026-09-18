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

# CH: быстрые MX первыми (gmail/icloud), локальные ISP после.
# gmx.ch первым сериализует весь прогон и съедает 180s wall — hit rate падает.
SWITZERLAND_VALIDATION_DOMAINS: tuple[str, ...] = (
    "gmail.com",
    "icloud.com",
    "gmx.ch",
    "bluewin.ch",
    "hotmail.com",
    "outlook.com",
    "sunrise.ch",
    "gmx.net",
    "hispeed.ch",
    "yahoo.com",
    "me.com",
    "hotmail.ch",
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
    if tid == "gag":
        from region import AQUA_DEFAULT_SERVICE

        return (AQUA_DEFAULT_SERVICE or "kleinanzeigen_de").strip()
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
    """CSM/Evoleum на DE → ebay.de; Hustle/GAG — площадка из Команды API."""
    from services.csm_catalog import is_verify_service
    from services.hustle_catalog import is_hustle_verify

    tid = (team_id or "").strip().lower()
    code = (service_code or "").strip()
    if tid in {"hustle", "gag"}:
        if tid == "hustle" and is_hustle_verify(code):
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


def switzerland_html_service(team_id: str = "") -> str:
    """Дефолт Швейцарии для HTML / GAG."""
    return "ricardo_ch"


def switzerland_html_service_for_code(service_code: str) -> str:
    """ricardo / tutti / anibis / post → *_ch."""
    from services.csm_catalog import parse_service_key

    code = (service_code or "").strip().lower()
    if not code:
        return switzerland_html_service()
    if code in {"ricardo_ch", "tutti_ch", "anibis_ch", "post_ch", "posta_ch"}:
        return "post_ch" if code == "posta_ch" else code
    if code in {"ricardo", "tutti", "anibis"}:
        return f"{code}_ch"
    if code in {"post", "posta", "post.ch"}:
        return "post_ch"
    if "_" in code:
        platform, _cc = parse_service_key(code)
        plat = (platform or "").strip().lower()
        if plat in {"ricardo", "tutti", "anibis"}:
            return f"{plat}_ch"
        if plat in {"post", "posta"}:
            return "post_ch"
    return switzerland_html_service()


def force_switzerland_html_service(team_id: str, service_code: str) -> str:
    """Verify оставляем; HTML/GAG CH по ricardo / tutti / anibis / post."""
    from services.csm_catalog import is_verify_service
    from services.hustle_catalog import is_hustle_verify

    tid = (team_id or "").strip().lower()
    code = (service_code or "").strip()
    if tid == "csm" and is_verify_service(code):
        return code
    if tid == "hustle" and is_hustle_verify(code):
        return code
    return switzerland_html_service_for_code(code)


def default_validation_domains_for(country: str) -> tuple[str, ...]:
    cc = normalize_country_id(country) or LEGACY_COUNTRY
    if cc == "de":
        return GERMANY_VALIDATION_DOMAINS
    if cc == "ch":
        return SWITZERLAND_VALIDATION_DOMAINS
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
