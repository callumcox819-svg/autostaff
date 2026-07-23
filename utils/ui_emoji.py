"""Premium (custom) emoji для кнопок и текста Telegram — icon_custom_emoji_id / tg-emoji."""

from __future__ import annotations

import json
import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from aiogram.types import InlineKeyboardButton, KeyboardButton

logger = logging.getLogger(__name__)

# Unicode fallback, если id не задан (локальная отладка)
_UNICODE_FALLBACK: dict[str, str] = {
    "settings": "⚙️",
    "quick_add": "⚡",
    "send": "▶️",
    "stop": "⏹",
    "status": "📊",
    "admin": "👑",
    "test_mail": "🧪",
    "back": "⬅️",
    "green": "🟢",
    "red": "🔴",
    "yellow": "🟡",
    "add": "➕",
    "delete": "🗑",
    "email": "📧",
    "proxy": "🌐",
    "key": "🔑",
    "profile": "🧾",
    "presets": "📄",
    "interval": "🧮",
    "hide": "🍀",
    "edit": "✏️",
    "ok": "✅",
    "fail": "❌",
    "wait": "⏳",
    "refresh": "🔄",
    "search": "🔍",
    "burst": "⚡",
    "puzzle": "🧩",
}


@lru_cache(maxsize=1)
def _load_emoji_ids() -> dict[str, str]:
    out: dict[str, str] = {}

    cfg_path = (os.getenv("PREMIUM_EMOJI_CONFIG") or "").strip()
    if not cfg_path:
        cfg_path = str(Path(__file__).resolve().parent.parent / "config" / "premium_emoji.json")

    p = Path(cfg_path)
    if p.is_file():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                for k, v in data.items():
                    sk = str(k).strip()
                    sv = str(v).strip()
                    if sk.startswith("_") or not sk or not sv.isdigit():
                        continue
                    out[sk] = sv
        except Exception:
            logger.exception("Failed to load premium emoji config: %s", p)

    for key, val in os.environ.items():
        if not key.startswith("EMOJI_"):
            continue
        sk = key[6:].lower()
        sv = (val or "").strip()
        if sk and sv.isdigit():
            out[sk] = sv

    return out


def emoji_id(key: str) -> str | None:
    return _load_emoji_ids().get((key or "").strip().lower())


def unicode_fallback(key: str) -> str:
    return _UNICODE_FALLBACK.get((key or "").strip().lower(), "")


def label(key: str, text: str, *, fallback_in_text: bool = True) -> str:
    """Текст кнопки: без unicode, если есть premium id (emoji рисуется отдельно)."""
    if emoji_id(key):
        return text
    if fallback_in_text:
        fb = unicode_fallback(key)
        return f"{fb} {text}".strip() if fb else text
    return text


def html_emoji(key: str, *, fallback: str | None = None) -> str:
    """Premium emoji в HTML-сообщениях бота."""
    eid = emoji_id(key)
    fb = fallback if fallback is not None else unicode_fallback(key)
    if eid:
        return f'<tg-emoji emoji-id="{eid}">{fb or "•"}</tg-emoji>'
    return fb or ""


def reply_button(key: str, text: str, *, style: str | None = None, **kwargs: Any) -> KeyboardButton:
    """
    Reply-клавиатура: premium icon + читаемый текст.
    style=primary/success/danger на клиентах часто прячет подпись — не используем.
    """
    eid = emoji_id(key)
    kw: dict[str, Any] = dict(kwargs)
    if eid:
        return KeyboardButton(text=text, icon_custom_emoji_id=eid, **kw)
    return KeyboardButton(text=label(key, text), **kw)


def inline_button(
    key: str,
    text: str,
    *,
    callback_data: str | None = None,
    url: str | None = None,
    style: str | None = None,
    **kwargs: Any,
) -> InlineKeyboardButton:
    eid = emoji_id(key)
    btn_text = text if eid else label(key, text)
    kw: dict[str, Any] = dict(kwargs)
    if style:
        kw["style"] = style
    if eid:
        kw["icon_custom_emoji_id"] = eid
    if callback_data is not None:
        kw["callback_data"] = callback_data
    if url is not None:
        kw["url"] = url
    return InlineKeyboardButton(text=btn_text, **kw)


def icon_button(key: str, *, callback_data: str, style: str | None = None) -> InlineKeyboardButton:
    """Компактная inline-кнопка только с premium-иконкой."""
    fb = unicode_fallback(key) or "•"
    return inline_button(key, fb, callback_data=callback_data, style=style)


def toggle_button(on: bool, caption: str, callback_data: str) -> InlineKeyboardButton:
    key = "green" if on else "red"
    eid = emoji_id(key)
    style = "success" if on else "danger"
    if eid:
        return InlineKeyboardButton(
            text=caption,
            icon_custom_emoji_id=eid,
            callback_data=callback_data,
            style=style,
        )
    fb = unicode_fallback(key)
    return InlineKeyboardButton(
        text=f"{fb} {caption}".strip(),
        callback_data=callback_data,
        style=style,
    )


def log_emoji_profile() -> None:
    ids = _load_emoji_ids()
    if ids:
        logger.info("Premium emoji keys loaded: %s", ", ".join(sorted(ids.keys())))
    else:
        logger.warning(
            "Premium emoji IDs not set — using Unicode fallback. "
            "Fill config/premium_emoji.json or EMOJI_* env vars."
        )
