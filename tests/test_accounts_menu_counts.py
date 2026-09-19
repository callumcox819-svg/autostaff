import unittest
from types import SimpleNamespace

from handlers.accounts import (
    account_status_counts,
    is_dead_inactive_status,
    is_mailing_active_status,
    is_smtp_paused_status,
)


class AccountStatusBucketsTests(unittest.TestCase):
    def test_buckets(self):
        self.assertTrue(is_mailing_active_status("active"))
        self.assertTrue(is_mailing_active_status(None))
        self.assertTrue(is_smtp_paused_status("smtp_blocked"))
        self.assertTrue(is_dead_inactive_status("error"))
        self.assertTrue(is_dead_inactive_status("bad"))
        self.assertFalse(is_dead_inactive_status("smtp_blocked"))
        self.assertFalse(is_dead_inactive_status("proxy_error"))

    def test_counts(self):
        accounts = [
            SimpleNamespace(status="active"),
            SimpleNamespace(status="enabled"),
            SimpleNamespace(status="smtp_blocked"),
            SimpleNamespace(status="error"),
            SimpleNamespace(status="proxy_error"),
        ]
        total, active, paused, inactive = account_status_counts(accounts)
        self.assertEqual(total, 5)
        self.assertEqual(active, 2)
        self.assertEqual(paused, 2)  # smtp_blocked + proxy_error
        self.assertEqual(inactive, 1)


if __name__ == "__main__":
    unittest.main()
