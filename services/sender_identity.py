"""Актуальное From-имя: только последнее сохранённое, без старых подписей."""

from __future__ import annotations

import json
import re
from typing import Iterable

SENDER_NAME_HISTORY_KEY = "sender_name_history"
_MAX_HISTORY = 24


def _norm(name: str) -> str:
    return " ".join((name or "").split()).strip()


def merge_sender_name_history(
    previous: Iterable[str],
    *,
    old_name: str,
    new_name: str,
) -> list[str]:
    """Старое имя в начало истории; текущее в списке не держим."""
    new_n = _norm(new_name)
    old_n = _norm(old_name)
    out: list[str] = []
    seen: set[str] = set()

    def _add(raw: str) -> None:
        s = _norm(raw)
        if not s:
            return
        key = s.casefold()
        if new_n and key == new_n.casefold():
            return
        if key in seen:
            return
        seen.add(key)
        out.append(s)

    _add(old_n)
    for item in previous:
        _add(item)
    return out[:_MAX_HISTORY]


_CLOSING_LINE_HINTS = frozenset(
    {
        "freundliche grüße",
        "freundliche grusse",
        "viele grüße",
        "beste grüße",
        "kind regards",
        "best regards",
        "thank you",
        "met vriendelijke groet",
        "groetjes",
        "dank je",
        "alvast bedankt",
        "com os melhores cumprimentos",
        "atenciosamente",
        "obrigado",
        "üdvözlettel",
        "udvozlettel",
    }
)


def strip_stale_sender_names(
    body: str,
    *,
    current_name: str,
    previous_names: Iterable[str] = (),
) -> str:
    """Убрать прошлые From-имена из пресета/подписи, оставить только current."""
    text = body or ""
    current = _norm(current_name)
    stale = [_norm(x) for x in previous_names if _norm(x)]
    if current:
        stale = [s for s in stale if s.casefold() != current.casefold()]
    for prev in sorted(stale, key=len, reverse=True):
        if len(prev) < 4:
            continue
        text = re.sub(re.escape(prev), "", text, flags=re.IGNORECASE)
    lines = text.split("\n")
    while lines and not lines[-1].strip():
        lines.pop()
    if lines:
        last = lines[-1].strip()
        words = last.split()
        last_key = " ".join(words).casefold()
        looks_name = (
            2 <= len(words) <= 4
            and all(w[:1].isalpha() for w in words)
            and last_key not in _CLOSING_LINE_HINTS
            and not last.endswith((".", "!", "?", ",", ";", ":"))
        )
        if looks_name and current and last.casefold() != current.casefold():
            lines[-1] = current
        elif looks_name and not current:
            lines.pop()
    text = "\n".join(lines)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


async def load_sender_name_history(session, user) -> list[str]:
    from services.user_settings import get_user_setting

    raw = await get_user_setting(session, user, SENDER_NAME_HISTORY_KEY)
    if not (raw or "").strip():
        return []
    try:
        data = json.loads(raw)
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    return [_norm(str(x)) for x in data if _norm(str(x))]


async def record_sender_name_change(session, user, new_name: str) -> list[str]:
    from services.user_settings import set_user_setting

    old = _norm(getattr(user, "sender_name", None) or "")
    hist = await load_sender_name_history(session, user)
    nxt = merge_sender_name_history(hist, old_name=old, new_name=new_name)
    await set_user_setting(session, user, SENDER_NAME_HISTORY_KEY, json.dumps(nxt, ensure_ascii=False))
    return nxt
