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

# CH: приоритет — локальные ISP (gmx.ch), дальше gmail/icloud.
# «Нет ящика» → следующий домен; GMX unknown/policy → скип семьи GMX, не стоп всего списка.
SWITZERLAND_VALIDATION_DOMAINS: tuple[str, ...] = (
    "gmx.ch",
    "gmail.com",
    "bluewin.ch",
    "icloud.com",
    "hotmail.com",
    "outlook.com",
    "sunrise.ch",
    "gmx.net",
    "hispeed.ch",
    "yahoo.com",
    "me.com",
    "hotmail.ch",
)

AUSTRIA_VALIDATION_DOMAINS: tuple[str, ...] = (
    "gmx.at",
    "gmail.com",
    "aon.at",
    "icloud.com",
    "outlook.at",
    "hotmail.com",
    "gmx.net",
    "chello.at",
)

# PT: OLX.pt — sapo/meo, потом gmail/icloud.
PORTUGAL_VALIDATION_DOMAINS: tuple[str, ...] = (
    "sapo.pt",
    "gmail.com",
    "icloud.com",
    "hotmail.com",
    "outlook.pt",
    "outlook.com",
    "meo.pt",
    "clix.pt",
    "netcabo.pt",
    "live.com.pt",
    "yahoo.pt",
    "me.com",
)

# HU: Jófogás — freemail/citromail, потом gmail/icloud.
HUNGARY_VALIDATION_DOMAINS: tuple[str, ...] = (
    "freemail.hu",
    "gmail.com",
    "citromail.hu",
    "icloud.com",
    "indamail.hu",
    "vipmail.hu",
    "outlook.com",
    "hotmail.com",
    "t-online.hu",
    "yahoo.com",
    "me.com",
)

# HR: Njuškalo — net.hr / t-com, потом gmail/icloud.
CROATIA_VALIDATION_DOMAINS: tuple[str, ...] = (
    "net.hr",
    "gmail.com",
    "t-com.hr",
    "icloud.com",
    "hotmail.com",
    "outlook.com",
    "iskon.hr",
    "yahoo.com",
    "optinet.hr",
    "me.com",
    "infonet.hr",
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
    """ricardo / tutti / anibis / post / markt.ch → HTML-папка *_ch (markt → post_ch)."""
    from services.csm_catalog import parse_service_key

    code = (service_code or "").strip().lower()
    if not code:
        return switzerland_html_service()
    if code in {"ricardo_ch", "tutti_ch", "anibis_ch", "post_ch"}:
        return code
    if code in {"posta_ch", "markt_ch"}:
        return "post_ch"
    if code in {"ricardo", "tutti", "anibis"}:
        return f"{code}_ch"
    if code in {"post", "posta", "post.ch"}:
        return "post_ch"
    if code in {"markt", "markt.ch"}:
        return "post_ch"
    if "_" in code:
        platform, _cc = parse_service_key(code)
        plat = (platform or "").strip().lower()
        if plat in {"ricardo", "tutti", "anibis"}:
            return f"{plat}_ch"
        if plat in {"post", "posta", "markt"}:
            return "post_ch"
    return switzerland_html_service()


def portugal_html_service(team_id: str = "") -> str:
    """Дефолт Португалии: OLX.pt."""
    _ = team_id
    return "olx_pt"


def portugal_html_service_for_code(service_code: str) -> str:
    """olx → olx_pt; остальные PT-площадки как {platform}_pt, иначе OLX."""
    from services.csm_catalog import parse_service_key

    code = (service_code or "").strip().lower()
    if not code:
        return portugal_html_service()
    if code in {"olx_pt", "olx", "olx.pt"}:
        return "olx_pt"
    if "_" in code:
        platform, cc = parse_service_key(code)
        plat = (platform or "").strip().lower()
        if plat == "olx":
            return "olx_pt"
        if cc == "pt" and plat:
            return f"{plat}_pt"
    if code.startswith("olx"):
        return "olx_pt"
    return portugal_html_service()


def force_portugal_html_service(team_id: str, service_code: str) -> str:
    from services.csm_catalog import is_verify_service
    from services.hustle_catalog import is_hustle_verify

    tid = (team_id or "").strip().lower()
    code = (service_code or "").strip()
    if tid == "csm" and is_verify_service(code):
        return code
    if tid == "hustle" and is_hustle_verify(code):
        return code
    return portugal_html_service_for_code(code)


def force_portugal_olx_service(team_id: str, service_code: str) -> str:
    """CSM на PT → olx_pt (Verify не трогаем)."""
    from services.csm_catalog import is_verify_service, make_service_key, parse_service_key

    tid = (team_id or "").strip().lower()
    code = (service_code or "").strip()
    if tid == "csm" and is_verify_service(code):
        return code
    if tid != "csm":
        return portugal_html_service_for_code(code)
    platform, cc = parse_service_key(code)
    plat = (platform or "").strip().lower()
    if plat == "olx":
        return "olx_pt"
    if cc == "pt" and plat in {"wallapop", "vinted", "depop", "ebay"}:
        return make_service_key(plat, "pt")
    return "olx_pt"


def hungary_html_service(team_id: str = "") -> str:
    """Дефолт Венгрии: Jófogás."""
    _ = team_id
    return "jofogas_hu"


def hungary_html_service_for_code(service_code: str) -> str:
    from services.csm_catalog import parse_service_key

    code = (service_code or "").strip().lower()
    if not code:
        return hungary_html_service()
    if code in {"jofogas_hu", "jofogas", "jofogas.hu"}:
        return "jofogas_hu"
    if "_" in code:
        platform, cc = parse_service_key(code)
        plat = (platform or "").strip().lower()
        if plat in {"jofogas", "jofogás"}:
            return "jofogas_hu"
        if cc == "hu" and plat:
            return f"{plat}_hu"
    if code.startswith("jofogas"):
        return "jofogas_hu"
    return hungary_html_service()


def force_hungary_html_service(team_id: str, service_code: str) -> str:
    from services.csm_catalog import is_verify_service
    from services.hustle_catalog import is_hustle_verify

    tid = (team_id or "").strip().lower()
    code = (service_code or "").strip()
    if tid == "csm" and is_verify_service(code):
        return code
    if tid == "hustle" and is_hustle_verify(code):
        return code
    return hungary_html_service_for_code(code)


def croatia_html_service(team_id: str = "") -> str:
    """Дефолт Хорватии (RPC): Njuškalo. Не Jófogás."""
    _ = team_id
    return "njuskalo_hr"


def croatia_html_service_for_code(service_code: str) -> str:
    from services.csm_catalog import parse_service_key

    code = (service_code or "").strip().lower()
    if not code:
        return croatia_html_service()
    if code in {"njuskalo_hr", "njuskalo", "njuskalo.hr"}:
        return "njuskalo_hr"
    if "_" in code:
        platform, cc = parse_service_key(code)
        plat = (platform or "").strip().lower()
        if plat == "njuskalo" or cc == "hr":
            return "njuskalo_hr"
    if code.startswith("njuskalo"):
        return "njuskalo_hr"
    return croatia_html_service()


def force_croatia_html_service(team_id: str, service_code: str) -> str:
    from services.csm_catalog import is_verify_service
    from services.hustle_catalog import is_hustle_verify

    tid = (team_id or "").strip().lower()
    code = (service_code or "").strip()
    if tid == "csm" and is_verify_service(code):
        return code
    if tid == "hustle" and is_hustle_verify(code):
        return code
    return croatia_html_service_for_code(code)


def force_croatia_njuskalo_service(team_id: str, service_code: str) -> str:
    """RPC на HR → Njuškalo (facebook оставляем)."""
    tid = (team_id or "").strip().lower()
    if tid == "rpc":
        from services.rpc_catalog import force_rpc_generate_service

        return force_rpc_generate_service("hr", service_code)
    return (service_code or "").strip() or "njuskalo_hr"


def force_hungary_jofogas_service(team_id: str, service_code: str) -> str:
    """BASTARD/RPC/CSM на HU → Jófogás (Verify не трогаем)."""
    from services.csm_catalog import is_verify_service, make_service_key, parse_service_key
    from services.bastard_catalog import BASTARD_DEFAULT_SERVICE

    tid = (team_id or "").strip().lower()
    code = (service_code or "").strip()
    if tid == "csm" and is_verify_service(code):
        return code
    if tid == "bastard":
        return code or BASTARD_DEFAULT_SERVICE
    if tid == "rpc":
        from services.rpc_catalog import force_rpc_generate_service

        return force_rpc_generate_service("hu", service_code)
    if tid != "csm":
        return hungary_html_service_for_code(code)
    platform, cc = parse_service_key(code)
    plat = (platform or "").strip().lower()
    if plat == "jofogas":
        return "jofogas_hu"
    if cc == "hu" and plat in {"vinted", "depop", "ebay", "facebook"}:
        return make_service_key(plat, "hu")
    return "jofogas_hu"


def force_switzerland_html_service(team_id: str, service_code: str) -> str:
    """Verify оставляем; HTML/GAG CH по ricardo / tutti / anibis / post."""
    from services.csm_catalog import is_verify_service
    from services.hustle_catalog import is_hustle_verify

    tid = (team_id or "").strip().lower()
    code = (service_code or "").strip()
    if tid == "gag":
        from services.gag_catalog import normalize_gag_service_code

        return switzerland_html_service_for_code(normalize_gag_service_code(code))
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
    if cc == "at":
        return AUSTRIA_VALIDATION_DOMAINS
    if cc == "pt":
        return PORTUGAL_VALIDATION_DOMAINS
    if cc == "hu":
        return HUNGARY_VALIDATION_DOMAINS
    if cc == "hr":
        return CROATIA_VALIDATION_DOMAINS
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
