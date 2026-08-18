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

    def test_unknown_is_api_failure_not_mailbox_missing(self):
        from services.validemail_validator import _is_api_failure

        self.assertTrue(
            _is_api_failure(
                False,
                {
                    "_http_status": 200,
                    "status": "unknown",
                    "reason": "timeout",
                    "isDeliverable": False,
                },
            )
        )
        self.assertTrue(
            _is_api_failure(
                False,
                {
                    "_http_status": 200,
                    "status": "unknown",
                    "reason": "other",
                    "isDeliverable": False,
                },
            )
        )
        self.assertFalse(
            _is_api_failure(
                False,
                {
                    "_http_status": 200,
                    "status": "undeliverable",
                    "reason": "invalid_smtp",
                    "isDeliverable": False,
                },
            )
        )

    def test_wave_retries_cancelled_even_if_one_undeliverable(self):
        from services.validemail_validator import _wave_seller_needs_api_retry

        emails = [
            "a@gmail.com",
            "b@gmail.com",
            "c@gmail.com",
        ]
        results = [
            (
                "a@gmail.com",
                False,
                {
                    "_http_status": 200,
                    "status": "undeliverable",
                    "reason": "invalid_smtp",
                },
            ),
            ("b@gmail.com", False, {"error": "cancelled", "_cancelled": True}),
            (
                "c@gmail.com",
                False,
                {"_http_status": 200, "status": "unknown", "reason": "timeout"},
            ),
        ]
        self.assertTrue(
            _wave_seller_needs_api_retry(results, emails, seller_already_found=False)
        )

    def test_retry_all_sellers_by_default(self):
        from unittest.mock import patch

        import os

        from services.validemail_keys import api_retry_max_sellers, combined_local_probe

        with patch.dict(os.environ, {"VALIDEMAIL_API_RETRY_MAX": ""}, clear=False):
            self.assertEqual(api_retry_max_sellers(), -1)
        with patch.dict(os.environ, {"VALIDEMAIL_COMBINED_LOCALS": ""}, clear=False):
            self.assertFalse(combined_local_probe())

    def test_domain_priority_one_domain_at_a_time(self):
        from services.validemail_validator import _domain_priority_waves

        waves = _domain_priority_waves(
            ["anna.mueller", "annamueller"],
            ["gmail.com", "icloud.com", "gmx.ch"],
        )
        self.assertEqual(
            [d for d, _w in waves],
            ["gmail.com", "icloud.com", "gmx.ch"],
        )
        self.assertEqual(
            waves[0][1],
            ["anna.mueller@gmail.com", "annamueller@gmail.com"],
        )
        self.assertTrue(all("@icloud.com" in e for e in waves[1][1]))
        self.assertFalse(any("@icloud.com" in e for e in waves[0][1]))

    def test_seven_keys_wall_uses_full_priority_list(self):
        from unittest.mock import patch

        import os

        from services.validemail_keys import max_domains_per_seller, validation_wall_sec

        with patch.dict(os.environ, {"VALIDEMAIL_MAX_DOMAINS_PROBE": "", "VALIDEMAIL_DEADLINE_SEC": ""}, clear=False):
            self.assertEqual(max_domains_per_seller(), 0)
            self.assertEqual(validation_wall_sec(7), 0.0)
        with patch.dict(os.environ, {"VALIDEMAIL_MAX_DOMAINS_PROBE": "0"}, clear=False):
            self.assertEqual(max_domains_per_seller(), 0)


if __name__ == "__main__":
    unittest.main()
