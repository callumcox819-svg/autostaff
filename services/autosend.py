"""Авто-рассылка: тумблер в настройках, шлёт всю очередь OfferEmail."""

from __future__ import annotations

import time

from services.user_settings import get_user_setting, set_user_setting

AUTO_SEND_KEY = "auto_send"
AUTO_SEND_CHAT_KEY = "auto_send_chat_id"

_pause_until: dict[int, float] = {}


def _truthy(raw: str | None) -> bool:
    return str(raw or "").strip().lower() in {"1", "true", "yes", "on", "y"}


async def is_auto_send_on(session, user) -> bool:
    return _truthy(await get_user_setting(session, user, AUTO_SEND_KEY))


async def set_auto_send_on(session, user, on: bool) -> None:
    await set_user_setting(session, user, AUTO_SEND_KEY, "1" if on else "0")


async def get_auto_send_chat_id(session, user) -> int | None:
    raw = (await get_user_setting(session, user, AUTO_SEND_CHAT_KEY) or "").strip()
    try:
        n = int(raw)
    except ValueError:
        return None
    return n if n else None


async def set_auto_send_chat_id(session, user, chat_id: int) -> None:
    await set_user_setting(session, user, AUTO_SEND_CHAT_KEY, str(int(chat_id)))


def pause_auto_send(tg_id: int, seconds: float = 90.0) -> None:
    _pause_until[int(tg_id)] = time.time() + max(0.0, float(seconds))


def clear_auto_send_pause(tg_id: int) -> None:
    _pause_until.pop(int(tg_id), None)


def auto_send_paused(tg_id: int) -> bool:
    until = _pause_until.get(int(tg_id), 0.0)
    return until > time.time()
