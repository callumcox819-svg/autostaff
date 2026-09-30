# -*- coding: utf-8 -*-
import unittest

from services.autosend import (
    auto_send_paused,
    clear_auto_send_pause,
    pause_auto_send,
)


class AutosendPauseTests(unittest.TestCase):
    def test_pause_then_clear(self):
        pause_auto_send(999001, 60)
        self.assertTrue(auto_send_paused(999001))
        clear_auto_send_pause(999001)
        self.assertFalse(auto_send_paused(999001))

    def test_expired_pause(self):
        pause_auto_send(999002, 0)
        self.assertFalse(auto_send_paused(999002))


if __name__ == "__main__":
    unittest.main()
