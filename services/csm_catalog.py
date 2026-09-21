"""Каталог CSM: сначала страна, затем сервисы этой страны.

serviceKey = {platform}_{country} | {platform}_verify_all
"""

from __future__ import annotations

import os

# (id, label, premium emoji key)
CSM_PLATFORMS: tuple[tuple[str, str, str], ...] = (
    ("depop", "Depop", "link"),
    ("vinted", "Vinted", "presets"),
    ("ebay", "eBay", "search"),
    ("kleinanzeigen", "Kleinanzeigen", "pin"),
    ("willhaben", "Willhaben", "compass"),
    ("laendleanzeiger", "Laendleanzeiger", "pin"),
    ("leboncoin", "Leboncoin", "price"),
    ("subito", "Subito", "burst"),
    ("marktplaats", "Marktplaats", "puzzle"),
    ("2dehands", "2dehands", "add"),
    ("wallapop", "Wallapop", "proxy"),
    ("gumtree", "Gumtree", "email"),
    ("olx", "OLX", "status"),
    ("blocket", "Blocket", "yellow"),
    ("dba", "DBA", "info"),
    ("facebook", "Facebook", "user"),
    ("mercari", "Mercari", "quick_add"),
    ("poshmark", "Poshmark", "ok"),
    ("etsy", "Etsy", "mail"),
    ("tutti", "Tutti", "hide"),
    ("ricardo", "Ricardo", "key"),
    ("anibis", "Anibis", "accounts"),
    ("markt", "Markt.ch", "mail"),
)

# Страны: (id, русское название, emoji key)
CSM_COUNTRIES: tuple[tuple[str, str, str], ...] = (
    ("nl", "Нидерланды", "compass"),
    ("be", "Бельгия", "compass"),
    ("de", "Германия", "compass"),
    ("at", "Австрия", "compass"),
    ("ch", "Швейцария", "compass"),
    ("fr", "Франция", "compass"),
    ("it", "Италия", "compass"),
    ("es", "Испания", "compass"),
    ("pt", "Португалия", "compass"),
    ("pl", "Польша", "compass"),
    ("se", "Швеция", "compass"),
    ("dk", "Дания", "compass"),
    ("uk", "Великобритания", "compass"),
    ("us", "США", "compass"),
    ("ca", "Канада", "compass"),
)

# Страна → сервисы (порядок = приоритет в UI)
CSM_COUNTRY_SERVICES: dict[str, tuple[str, ...]] = {
    "nl": ("marktplaats", "2dehands", "vinted", "depop", "ebay", "facebook"),
    "be": ("2dehands", "marktplaats", "vinted", "depop", "ebay", "facebook"),
    "de": ("kleinanzeigen", "ebay", "vinted", "depop", "facebook"),
    "at": ("willhaben", "laendleanzeiger", "ebay", "vinted", "depop", "facebook"),
    "ch": ("tutti", "ricardo", "anibis", "markt", "ebay", "vinted", "depop"),
    "fr": ("leboncoin", "vinted", "depop", "ebay", "facebook"),
    "it": ("subito", "vinted", "depop", "ebay", "facebook"),
    "es": ("wallapop", "vinted", "depop", "ebay", "facebook"),
    "pt": ("olx", "wallapop", "vinted", "depop", "ebay"),
    "pl": ("olx", "vinted", "depop", "ebay", "facebook"),
    "se": ("blocket", "vinted", "depop", "ebay", "facebook"),
    "dk": ("dba", "vinted", "depop", "ebay", "facebook"),
    "uk": ("gumtree", "ebay", "vinted", "depop", "facebook", "etsy"),
    "us": ("depop", "ebay", "mercari", "poshmark", "etsy", "vinted", "facebook"),
    "ca": ("ebay", "depop", "vinted", "facebook", "etsy"),
}

CSM_VERIFY_SUFFIX = "verify_all"

_PLATFORM_BY_ID = {p: (p, label, emoji) for p, label, emoji in CSM_PLATFORMS}
_COUNTRY_IDS = {c for c, _, _ in CSM_COUNTRIES}


def list_csm_countries() -> list[tuple[str, str, str]]:
    return list(CSM_COUNTRIES)


def list_csm_platforms() -> list[tuple[str, str, str]]:
    raw = (os.getenv("CSM_PLATFORMS") or "").strip()
    if not raw:
        return list(CSM_PLATFORMS)
    out: list[tuple[str, str, str]] = []
    for part in raw.split(","):
        pid = part.strip().lower()
        if not pid:
            continue
        out.append(_PLATFORM_BY_ID.get(pid, (pid, pid.capitalize(), "link")))
    return out or list(CSM_PLATFORMS)


def platforms_for_country(country_id: str) -> list[tuple[str, str, str]]:
    """Сервисы для страны: (platform_id, label, emoji_key)."""
    cc = (country_id or "").strip().lower()
    ids = CSM_COUNTRY_SERVICES.get(cc) or ("depop", "ebay", "vinted")
    known = {p: (p, label, emoji) for p, label, emoji in list_csm_platforms()}
    out: list[tuple[str, str, str]] = []
    for pid in ids:
        out.append(known.get(pid, (pid, pid.capitalize(), "link")))
    return out


def platform_label(platform_id: str) -> str:
    meta = _PLATFORM_BY_ID.get((platform_id or "").strip().lower())
    if meta:
        return meta[1]
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
        return "marktplaats", "nl"
    platform, rest = s.split("_", 1)
    if rest in {"verify", CSM_VERIFY_SUFFIX}:
        return platform or "depop", CSM_VERIFY_SUFFIX
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
    return f"{country_label(country)} · {platform_label(platform)}"


def is_verify_service(service_code: str | None) -> bool:
    _, country = parse_service_key(service_code)
    return country == CSM_VERIFY_SUFFIX
