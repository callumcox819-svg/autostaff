"""Региональные настройки бота (Швейцария / GAG)."""

from __future__ import annotations

import os

BOT_DISPLAY_NAME = "GAG Bot"
MARKETPLACE_NAME = "ricardo.ch / tutti.ch"
TEAM_NAME = "GAG"

# Коды service в GAG API (APEX): ricardo_ch, tutti_ch
AQUA_DEFAULT_SERVICE = (os.getenv("AQUA_DEFAULT_SERVICE", "ricardo_ch") or "ricardo_ch").strip()

HTML_DATA_DIR = "HTMLch"

DEFAULT_VALIDATION_DOMAINS: tuple[str, ...] = (
    "gmail.com",
    "hotmail.com",
    "outlook.com",
    "yahoo.com",
    "icloud.com",
    "bluewin.ch",
    "sunrise.ch",
    "gmx.ch",
    "gmx.net",
    "web.de",
    "hispeed.ch",
    "swissonline.ch",
    "me.com",
)


def format_item_price(price: str) -> str:
    """Цена в письмах/HTML: CHF, если валюта не указана."""
    p = (price or "").strip()
    if not p:
        return ""
    upper = p.upper()
    if upper.startswith("CHF") or "fr." in p.lower() or "sfr" in upper:
        return p
    if any(upper.startswith(c) for c in ("EUR", "USD", "GBP", "NOK", "SEK", "DKK")):
        return p
    if "€" in p:
        return p
    return f"CHF {p}"
