from unittest.mock import MagicMock

from aiogram.types import Message

from middlewares.bot_access import (
    _ACCESS_CACHE,
    _bypass_access_db_check,
    _cached_access,
    invalidate_access_cache,
)


def _msg(text: str = "") -> MagicMock:
    m = MagicMock(spec=Message)
    m.text = text
    m.document = None
    return m


def test_send_bypasses_busy_db_gate():
    assert _bypass_access_db_check(_msg("/send"))
    assert _bypass_access_db_check(_msg("/send@mybot"))
    assert _bypass_access_db_check(_msg("/menu"))


def test_cached_access_ttl():
    invalidate_access_cache()
    _ACCESS_CACHE[42] = (False, True, __import__("time").monotonic())
    assert _cached_access(42, max_age_sec=60) == (False, True)
    _ACCESS_CACHE[42] = (False, True, __import__("time").monotonic() - 9999)
    assert _cached_access(42, max_age_sec=60) is None
    assert _cached_access(42, max_age_sec=20000) == (False, True)
