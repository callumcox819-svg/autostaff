"""ValidEmail API v1 response normalization (api-doc schema)."""
from __future__ import annotations

import unittest

from services.validemail_fast import _normalize_ok


class ValidEmailNormalizeTests(unittest.TestCase):
    def test_deliverable_isDeliverable(self):
        self.assertTrue(
            _normalize_ok(
                {
                    "email": "a@b.com",
                    "status": "deliverable",
                    "reason": "accepted",
                    "isDeliverable": True,
                    "isFormatValid": True,
                    "isDomainValid": True,
                }
            )
        )

    def test_transient_timeout_not_ok(self):
        self.assertFalse(
            _normalize_ok(
                {
                    "status": "unknown",
                    "reason": "timeout",
                    "isDeliverable": False,
                }
            )
        )

    def test_deliverable_string_flag(self):
        self.assertTrue(
            _normalize_ok(
                {
                    "status": "deliverable",
                    "reason": "accepted",
                    "isDeliverable": "true",
                    "isFormatValid": True,
                    "isDomainValid": True,
                }
            )
        )
        self.assertFalse(
            _normalize_ok(
                {
                    "status": "undeliverable",
                    "reason": "invalid_smtp",
                    "isDeliverable": False,
                    "isFormatValid": True,
                    "isDomainValid": True,
                }
            )
        )


    def test_risky_accept_in_traffic_mode(self):
        import os
        from unittest.mock import patch

        payload = {
            "status": "risky",
            "reason": "catch_all",
            "isDeliverable": False,
            "isFormatValid": True,
            "isDomainValid": True,
        }
        with patch.dict(os.environ, {"VALIDEMAIL_ACCEPT_RISKY": "", "VALIDEMAIL_TRAFFIC_MODE": "1"}):
            self.assertTrue(_normalize_ok(payload))
        with patch.dict(os.environ, {"VALIDEMAIL_ACCEPT_RISKY": "0", "VALIDEMAIL_TRAFFIC_MODE": "1"}):
            self.assertFalse(_normalize_ok(payload))


if __name__ == "__main__":
    unittest.main()
