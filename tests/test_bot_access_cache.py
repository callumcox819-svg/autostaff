from middlewares.bot_access import (
    _ACCESS_CACHE,
    _bypass_access_db_check,
    _cached_access,
    invalidate_access_cache,
)


class _Msg:
    def __init__(self, text: str = "", document=None):
        self.text = text
        self.document = document
        self.chat = type("C", (), {"type": "private"})()
        self.pinned_message = None
        self.new_chat_members = None
        self.left_chat_member = None
        self.group_chat_created = False
        self.supergroup_chat_created = False
        self.migrate_to_chat_id = None
        self.migrate_from_chat_id = None


def test_send_bypasses_busy_db_gate():
    assert _bypass_access_db_check(_Msg("/send"))
    assert _bypass_access_db_check(_Msg("/send@mybot"))
    assert _bypass_access_db_check(_Msg("/menu"))


def test_cached_access_ttl():
    invalidate_access_cache()
    _ACCESS_CACHE[42] = (False, True, __import__("time").monotonic())
    assert _cached_access(42, max_age_sec=60) == (False, True)
    _ACCESS_CACHE[42] = (False, True, __import__("time").monotonic() - 9999)
    assert _cached_access(42, max_age_sec=60) is None
    assert _cached_access(42, max_age_sec=20000) == (False, True)
