"""Фоновые задачи на пользователя — чтобы кнопки не блокировали polling."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Awaitable

logger = logging.getLogger(__name__)

_tasks: dict[tuple[int, str], asyncio.Task] = {}
_started_at: dict[tuple[int, str], float] = {}


def is_running(user_id: int, key: str) -> bool:
    t = _tasks.get((int(user_id), str(key)))
    return t is not None and not t.done()


def running_since(user_id: int, key: str) -> float | None:
    if not is_running(user_id, key):
        return None
    return _started_at.get((int(user_id), str(key)))


def cancel(user_id: int, key: str) -> bool:
    uid = int(user_id)
    k = str(key)
    t = _tasks.get((uid, k))
    if t is None or t.done():
        _tasks.pop((uid, k), None)
        _started_at.pop((uid, k), None)
        return False
    t.cancel()
    return True


async def _wrap(user_id: int, key: str, coro: Awaitable[Any]) -> None:
    try:
        await coro
    except asyncio.CancelledError:
        logger.warning("background job cancelled user_id=%s key=%s", user_id, key)
        raise
    except Exception:
        logger.exception("background job failed user_id=%s key=%s", user_id, key)
    finally:
        _tasks.pop((int(user_id), str(key)), None)
        _started_at.pop((int(user_id), str(key)), None)


def start(user_id: int, key: str, coro: Awaitable[Any]) -> bool:
    """Запустить фоновую задачу. False — такая же уже выполняется."""
    uid = int(user_id)
    k = str(key)
    if is_running(uid, k):
        return False
    task = asyncio.create_task(_wrap(uid, k, coro))
    _tasks[(uid, k)] = task
    _started_at[(uid, k)] = time.time()
    return True
