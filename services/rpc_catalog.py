"""Каталог RPC (Continental Group Rental).

Документация: https://docs.continental-group-rental.com/endpoints/geo
Генерация: POST /api/v1/ad/create
Венгрия доступна и здесь, и в BASTARD (разные API).
"""

from __future__ import annotations

RPC_COUNTRIES: tuple[tuple[str, str, str], ...] = (
    ("hu", "Венгрия", "compass"),
)

# (service_code для /geo, label, emoji)
RPC_COUNTRY_SERVICES: dict[str, tuple[tuple[str, str, str], ...]] = {
    "hu": (
        ("jofogas", "Jófogás", "pin"),
        ("facebook", "Facebook", "user"),
    ),
}

RPC_DEFAULT_SERVICE = "jofogas"

_COUNTRY_IDS = {c for c, _, _ in RPC_COUNTRIES}
_SERVICE_IDS = {
    sid for rows in RPC_COUNTRY_SERVICES.values() for sid, _, _ in rows
}


def list_rpc_countries() -> list[tuple[str, str, str]]:
    return list(RPC_COUNTRIES)


def rpc_country_label(country_id: str) -> str:
    cc = (country_id or "").strip().lower()
    for cid, label, _ in RPC_COUNTRIES:
        if cid == cc:
            return label
    return (country_id or "—").upper()


def parse_rpc_service(service_code: str | None) -> tuple[str, str]:
    """→ (service_code для /ad/create, country). jofogas_hu → jofogas."""
    s = (service_code or "").strip().lower()
    if not s:
        return RPC_DEFAULT_SERVICE, "hu"
    if s in {"jofogas_hu", "jofogas.hu"}:
        return "jofogas", "hu"
    if s in {"facebook_hu", "facebook.com"}:
        return "facebook", "hu"
    if "_" in s:
        plat, country = s.rsplit("_", 1)
        if country in _COUNTRY_IDS:
            return (plat if plat in _SERVICE_IDS else s), country
    if s in _SERVICE_IDS:
        return s, "hu"
    return s, "hu"


def platforms_for_rpc_country(country_id: str) -> list[tuple[str, str, str]]:
    cc = (country_id or "").strip().lower()
    rows = RPC_COUNTRY_SERVICES.get(cc) or RPC_COUNTRY_SERVICES["hu"]
    return list(rows)


def rpc_service_meta(service_code: str | None) -> tuple[str, str, str]:
    code, country = parse_rpc_service(service_code)
    for sid, label, emoji in platforms_for_rpc_country(country):
        if sid == code:
            return sid, label, emoji
    return code, code, "link"


def rpc_service_label(service_code: str | None) -> str:
    code, country = parse_rpc_service(service_code)
    _sid, label, _e = rpc_service_meta(code)
    return f"{rpc_country_label(country)} · {label}"


def rpc_api_service_code(service_code: str | None) -> str:
    return parse_rpc_service(service_code)[0]


def is_rpc_service_code(service_code: str | None) -> bool:
    code, _cc = parse_rpc_service(service_code)
    return code in _SERVICE_IDS
