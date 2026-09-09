"""Каталог площадок CSM (meow network) — serviceKey = {platform}_{country|verify_all}."""

from __future__ import annotations

import os

# (id, label, premium emoji key)
CSM_PLATFORMS: tuple[tuple[str, str, str], ...] = (
    ("depop", "Depop", "link"),
    ("vinted", "Vinted", "presets"),
    ("ebay", "eBay", "search"),
    ("kleinanzeigen", "Kleinanzeigen", "pin"),
    ("willhaben", "Willhaben", "compass"),
    ("leboncoin", "Leboncoin", "price"),
    ("subito", "Subito", "burst"),
    ("marktplaats", "Marktplaats", "puzzle"),
    ("2dehands", "2dehands", "green"),
    ("wallapop", "Wallapop", "proxy"),
    ("gumtree", "Gumtree", "email"),
    ("olx", "OLX", "status"),
    ("blocket", "Blocket", "yellow"),
    ("dba", "DBA", "info"),
    ("facebook", "Facebook", "user"),
    ("mercari", "Mercari", "add"),
    ("poshmark", "Poshmark", "ok"),
    ("etsy", "Etsy", "mail"),
    ("tutti", "Tutti", "hide"),
    ("ricardo", "Ricardo", "key"),
)

# ISO-подобные коды, которые принимает slug-парсер CSM
CSM_COUNTRIES: tuple[tuple[str, str, str], ...] = (
    ("us", "USA", "compass"),
    ("uk", "UK", "compass"),
    ("ca", "Canada", "compass"),
    ("de", "Germany", "compass"),
    ("at", "Austria", "compass"),
    ("ch", "Switzerland", "compass"),
    ("fr", "France", "compass"),
    ("it", "Italy", "compass"),
    ("es", "Spain", "compass"),
    ("nl", "Netherlands", "compass"),
    ("be", "Belgium", "compass"),
    ("pl", "Poland", "compass"),
    ("se", "Sweden", "compass"),
    ("dk", "Denmark", "compass"),
    ("pt", "Portugal", "compass"),
)

CSM_VERIFY_SUFFIX = "verify_all"

_PLATFORM_IDS = {p for p, _, _ in CSM_PLATFORMS}
_COUNTRY_IDS = {c for c, _, _ in CSM_COUNTRIES}


def _env_platforms() -> list[tuple[str, str, str]] | None:
    """Опционально: CSM_PLATFORMS=depop,vinted,ebay"""
    raw = (os.getenv("CSM_PLATFORMS") or "").strip()
    if not raw:
        return None
    out: list[tuple[str, str, str]] = []
    known = {p: (p, label, emoji) for p, label, emoji in CSM_PLATFORMS}
    for part in raw.split(","):
        pid = part.strip().lower()
        if not pid:
            continue
        if pid in known:
            out.append(known[pid])
        else:
            out.append((pid, pid.capitalize(), "link"))
    return out or None


def list_csm_platforms() -> list[tuple[str, str, str]]:
    return list(_env_platforms() or CSM_PLATFORMS)


def list_csm_countries() -> list[tuple[str, str, str]]:
    return list(CSM_COUNTRIES)


def platform_label(platform_id: str) -> str:
    for pid, label, _ in list_csm_platforms():
        if pid == platform_id:
            return label
    return (platform_id or "—").capitalize()


def country_label(country_id: str) -> str:
    if country_id == CSM_VERIFY_SUFFIX or country_id == "verify":
        return "Verify"
    for cid, label, _ in CSM_COUNTRIES:
        if cid == country_id:
            return label
    return (country_id or "—").upper()


def parse_service_key(service_code: str | None) -> tuple[str, str]:
    """→ (platform, country|verify_all)."""
    s = (service_code or "").strip().lower()
    if not s or "_" not in s:
        return "depop", "us"
    platform, rest = s.split("_", 1)
    if rest == "verify" or rest == CSM_VERIFY_SUFFIX:
        return platform or "depop", CSM_VERIFY_SUFFIX
    if platform not in _PLATFORM_IDS and platform not in {p for p, _, _ in list_csm_platforms()}:
        # unknown platform still keep as-is
        pass
    if rest not in _COUNTRY_IDS and rest != CSM_VERIFY_SUFFIX:
        # keep raw suffix
        return platform, rest
    return platform, rest


def make_service_key(platform: str, country: str) -> str:
    p = (platform or "depop").strip().lower()
    c = (country or "us").strip().lower()
    if c in {"verify", CSM_VERIFY_SUFFIX}:
        return f"{p}_{CSM_VERIFY_SUFFIX}"
    return f"{p}_{c}"


def service_key_label(service_code: str | None) -> str:
    platform, country = parse_service_key(service_code)
    if country == CSM_VERIFY_SUFFIX:
        return f"{platform_label(platform)} · Verify"
    return f"{platform_label(platform)} · {country_label(country)}"


def is_verify_service(service_code: str | None) -> bool:
    _, country = parse_service_key(service_code)
    return country == CSM_VERIFY_SUFFIX
