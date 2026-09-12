"""Региональные настройки бота (нейтральные; сервисы/API задаются env)."""

from __future__ import annotations

import os

BOT_DISPLAY_NAME = (os.getenv("BOT_DISPLAY_NAME") or "Mail Bot").strip() or "Mail Bot"
MARKETPLACE_NAME = (os.getenv("MARKETPLACE_NAME") or "").strip()
TEAM_NAME = (os.getenv("TEAM_NAME") or "").strip()

# Код сервиса по умолчанию (пустой — первая папка data/HTML/ или AQUA_SERVICES)
AQUA_DEFAULT_SERVICE = (os.getenv("AQUA_DEFAULT_SERVICE") or "marktplaats_nl").strip()

# HTML-ответы: data/HTML/<service>/…
HTML_DATA_DIR = (os.getenv("HTML_DATA_DIR") or "HTML").strip() or "HTML"

# Дефолтные домены валидации, если у пользователя пустой список
DEFAULT_VALIDATION_DOMAINS: tuple[str, ...] = (
    "gmail.com",
    "hotmail.com",
    "outlook.com",
    "yahoo.com",
    "icloud.com",
    "gmx.de",
    "gmx.net",
    "web.de",
    "me.com",
)


def format_item_price(price: str) -> str:
    """Цена для payload генерации — как есть, без принудительной валюты."""
    return (price or "").strip()
