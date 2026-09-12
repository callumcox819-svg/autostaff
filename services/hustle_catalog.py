"""Каталог Hustle Castle (INC-CORE): страна → сервисы.

Документация: https://docs.inc-core.com/api/docs
Паттерны — как в «Список сервисов». eBay DE в их списке нет,
поэтому ebay_de уходит в кастомную генерацию (customservice_de).
"""

from __future__ import annotations

# (id, label, emoji key)
HUSTLE_COUNTRIES: tuple[tuple[str, str, str], ...] = (
    ("de", "Германия", "compass"),
)

# (service_code, label, emoji, mode)  mode: fast | lonely | custom | verify
HUSTLE_COUNTRY_SERVICES: dict[str, tuple[tuple[str, str, str, str], ...]] = {
    "de": (
        ("kleinanzeigen_de", "Kleinanzeigen", "pin", "fast"),
        ("ebay_de", "eBay", "search", "custom"),
        ("vinted_de", "Vinted", "presets", "fast"),
        ("facebook_de", "Facebook", "user", "lonely"),
        ("kleinanzeigenverif_de", "Kleinanzeigen Verif", "ok", "verify"),
        ("quoka_de", "Quoka", "price", "fast"),
        ("markt_de", "Markt", "puzzle", "fast"),
    ),
}

HUSTLE_DEFAULT_SERVICE = "kleinanzeigen_de"

# Брендинг eBay для POST /api/order/generate/custom
EBAY_DE_CUSTOM = {
    "service": "customservice_de",
    "platformName": "eBay",
    "platformFavicon": "https://upload.wikimedia.org/wikipedia/commons/thumb/1/1b/EBay_logo.svg/256px-EBay_logo.svg.png",
    "platformColor": "#E53238",
    "platformLogo": "https://upload.wikimedia.org/wikipedia/commons/thumb/1/1b/EBay_logo.svg/512px-EBay_logo.svg.png",
    "platformMethod": "2.0",
    "platformCountry": "de",
}

_COUNTRY_IDS = {c for c, _, _ in HUSTLE_COUNTRIES}


def list_hustle_countries() -> list[tuple[str, str, str]]:
    return list(HUSTLE_COUNTRIES)


def hustle_country_label(country_id: str) -> str:
    cc = (country_id or "").strip().lower()
    for cid, label, _ in HUSTLE_COUNTRIES:
        if cid == cc:
            return label
    return (country_id or "—").upper()


def parse_hustle_service(service_code: str | None) -> tuple[str, str]:
    """→ (service_code, country)."""
    s = (service_code or "").strip().lower()
    if not s:
        return HUSTLE_DEFAULT_SERVICE, "de"
    if "_" in s:
        country = s.rsplit("_", 1)[-1]
        if country in _COUNTRY_IDS:
            return s, country
    return s, "de"


def platforms_for_hustle_country(country_id: str) -> list[tuple[str, str, str, str]]:
    cc = (country_id or "").strip().lower()
    rows = HUSTLE_COUNTRY_SERVICES.get(cc) or HUSTLE_COUNTRY_SERVICES["de"]
    return list(rows)


def hustle_service_meta(service_code: str | None) -> tuple[str, str, str, str]:
    code, country = parse_hustle_service(service_code)
    for sid, label, emoji, mode in platforms_for_hustle_country(country):
        if sid == code:
            return sid, label, emoji, mode
    return code, code, "link", "lonely"


def hustle_service_label(service_code: str | None) -> str:
    code, country = parse_hustle_service(service_code)
    _sid, label, _e, _mode = hustle_service_meta(code)
    return f"{hustle_country_label(country)} · {label}"


def hustle_generate_mode(service_code: str | None) -> str:
    return hustle_service_meta(service_code)[3]


def is_hustle_verify(service_code: str | None) -> bool:
    return hustle_generate_mode(service_code) == "verify"


def is_hustle_fast(service_code: str | None) -> bool:
    return hustle_generate_mode(service_code) == "fast"


def is_hustle_custom(service_code: str | None) -> bool:
    return hustle_generate_mode(service_code) == "custom"
