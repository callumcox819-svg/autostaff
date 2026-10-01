"""Повтор при Telegram 429 RetryAfter — иначе /start и меню рвутся на полуслове."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import TypeVar

from aiogram.exceptions import TelegramRetryAfter

logger = logging.getLogger(__name__)

T = TypeVar("T")


def retry_after_seconds(exc: TelegramRetryAfter, *, cap: float = 25.0) -> float:
    raw = getattr(exc, "retry_after", None)
    try:
        sec = float(raw)
    except (TypeError, ValueError):
        sec = 1.0
    return min(max(sec, 0.4), cap)


async def tg_call(factory: Callable[[], Awaitable[T]], *, retries: int = 2, cap: float = 25.0) -> T:
    last: TelegramRetryAfter | None = None
    for attempt in range(retries + 1):
        try:
            return await factory()
        except TelegramRetryAfter as e:
            last = e
            wait = retry_after_seconds(e, cap=cap)
            logger.warning("TelegramRetryAfter wait=%.1fs attempt=%s", wait, attempt + 1)
            await asyncio.sleep(wait)
    assert last is not None
    raise last
