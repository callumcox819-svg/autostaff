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

    def test_undeliverable_invalid_smtp(self):
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


if __name__ == "__main__":
    unittest.main()
