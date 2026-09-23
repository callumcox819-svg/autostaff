"""Каталог BASTARD (INC-CORE, та же дока что Hustle Castle).

Документация: https://docs.inc-core.com/api/docs
API: https://traff.inc-core.com
Венгрия — Jófogás (jofogas_hu, FAST).
"""

from __future__ import annotations

BASTARD_COUNTRIES: tuple[tuple[str, str, str], ...] = (
    ("hu", "Венгрия", "compass"),
)

# (service_code, label, emoji, mode)  mode: fast | lonely | custom | verify
BASTARD_COUNTRY_SERVICES: dict[str, tuple[tuple[str, str, str, str], ...]] = {
    "hu": (
        ("jofogas_hu", "Jófogás", "pin", "fast"),
        ("facebook_hu", "Facebook", "user", "lonely"),
    ),
}

BASTARD_DEFAULT_SERVICE = "jofogas_hu"

_COUNTRY_IDS = {c for c, _, _ in BASTARD_COUNTRIES}


def list_bastard_countries() -> list[tuple[str, str, str]]:
    return list(BASTARD_COUNTRIES)


def bastard_country_label(country_id: str) -> str:
    cc = (country_id or "").strip().lower()
    for cid, label, _ in BASTARD_COUNTRIES:
        if cid == cc:
            return label
    return (country_id or "—").upper()


def parse_bastard_service(service_code: str | None) -> tuple[str, str]:
    s = (service_code or "").strip().lower()
    if not s:
        return BASTARD_DEFAULT_SERVICE, "hu"
    if "_" in s:
        country = s.rsplit("_", 1)[-1]
        if country in _COUNTRY_IDS:
            return s, country
    return s, "hu"


def platforms_for_bastard_country(country_id: str) -> list[tuple[str, str, str, str]]:
    cc = (country_id or "").strip().lower()
    rows = BASTARD_COUNTRY_SERVICES.get(cc) or BASTARD_COUNTRY_SERVICES["hu"]
    return list(rows)


def bastard_service_meta(service_code: str | None) -> tuple[str, str, str, str]:
    code, country = parse_bastard_service(service_code)
    for sid, label, emoji, mode in platforms_for_bastard_country(country):
        if sid == code:
            return sid, label, emoji, mode
    return code, code, "link", "lonely"


def bastard_service_label(service_code: str | None) -> str:
    code, country = parse_bastard_service(service_code)
    _sid, label, _e, _mode = bastard_service_meta(code)
    return f"{bastard_country_label(country)} · {label}"


def bastard_generate_mode(service_code: str | None) -> str:
    return bastard_service_meta(service_code)[3]


def is_bastard_verify(service_code: str | None) -> bool:
    return bastard_generate_mode(service_code) == "verify"


def is_bastard_fast(service_code: str | None) -> bool:
    return bastard_generate_mode(service_code) == "fast"


def is_bastard_custom(service_code: str | None) -> bool:
    return bastard_generate_mode(service_code) == "custom"
