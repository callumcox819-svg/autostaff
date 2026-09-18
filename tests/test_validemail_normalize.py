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
        with patch.dict(
            os.environ,
            {
                "VALIDEMAIL_ACCEPT_RISKY": "",
                "VALIDEMAIL_TRAFFIC_MODE": "1",
                "VALIDEMAIL_URL": "https://validemail.co/api/v1/validate",
                "VALIDEMAIL_MAILCHECK": "0",
            },
        ):
            self.assertTrue(_normalize_ok(payload))
        with patch.dict(os.environ, {"VALIDEMAIL_ACCEPT_RISKY": "0", "VALIDEMAIL_TRAFFIC_MODE": "1"}):
            self.assertFalse(_normalize_ok(payload))
        with patch.dict(
            os.environ,
            {
                "VALIDEMAIL_ACCEPT_RISKY": "",
                "VALIDEMAIL_TRAFFIC_MODE": "1",
                "VALIDEMAIL_URL": "https://validator-production-7106.up.railway.app/api/v1/validate",
                "VALIDEMAIL_MAILCHECK": "",
            },
        ):
            self.assertFalse(_normalize_ok(payload))

    def test_mailcheck_build_request_bearer_optional_and_timeout(self):
        import os
        from unittest.mock import patch

        from services.validemail_fast import _build_request

        url = "https://validator-production-7106.up.railway.app/api/v1/validate"
        with patch.dict(os.environ, {"VALIDEMAIL_API_TIMEOUT": "8"}, clear=False):
            headers, params = _build_request(url, "mailcheck", "a@b.com")
            self.assertNotIn("Authorization", headers)
            self.assertEqual(params.get("email"), "a@b.com")
            self.assertEqual(params.get("timeout"), "8")
            self.assertNotIn("api_key", params)

            headers2, _ = _build_request(url, "real-secret", "a@b.com")
            self.assertEqual(headers2.get("Authorization"), "Bearer real-secret")

            headers3, params3 = _build_request(url, "", "a@b.com")
            self.assertNotIn("Authorization", headers3)
            self.assertEqual(params3.get("email"), "a@b.com")

    def test_mailcheck_empty_key_resolves_dummy(self):
        import os
        from unittest.mock import patch

        from services.validemail_keys import resolve_validemail_api_keys

        with patch.dict(
            os.environ,
            {
                "VALIDEMAIL_URL": "https://validator-production-7106.up.railway.app/api/v1/validate",
                "VALIDEMAIL_MAILCHECK": "",
            },
            clear=False,
        ):
            with patch("services.validemail_keys.keys_from_config", return_value=[]):
                self.assertEqual(resolve_validemail_api_keys(), ["mailcheck"])

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
            self.assertEqual(api_retry_max_sellers(), 0)
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

    def test_wave_verdict_unknown_does_not_look_like_no_mailbox(self):
        from services.validemail_validator import _domain_wave_verdict

        pending = ["a@gmail.com", "b@gmail.com"]
        unknown = [
            (
                "a@gmail.com",
                False,
                {"_http_status": 200, "status": "unknown", "reason": "timeout"},
            ),
            (
                "b@gmail.com",
                False,
                {
                    "_http_status": 200,
                    "status": "undeliverable",
                    "reason": "invalid_smtp",
                },
            ),
        ]
        self.assertEqual(_domain_wave_verdict(unknown, pending), "unknown")
        nos = [
            (
                "a@gmail.com",
                False,
                {
                    "_http_status": 200,
                    "status": "undeliverable",
                    "reason": "invalid_smtp",
                },
            ),
            (
                "b@gmail.com",
                False,
                {
                    "_http_status": 200,
                    "status": "undeliverable",
                    "reason": "invalid_smtp",
                },
            ),
        ]
        self.assertEqual(_domain_wave_verdict(nos, pending), "no")

    def test_http_200_unknown_does_not_retry_same_domain(self):
        from services.validemail_fast import _is_transient_failure
        from services.validemail_validator import _should_retry_same_domain

        unknown = {
            "_http_status": 200,
            "status": "unknown",
            "reason": "timeout",
            "isDeliverable": False,
        }
        self.assertFalse(_is_transient_failure(unknown))
        self.assertFalse(_should_retry_same_domain(False, unknown))
        self.assertTrue(
            _should_retry_same_domain(False, {"_http_status": 429, "error": "rate limit"})
        )

    def test_seven_keys_wall_uses_full_priority_list(self):
        from unittest.mock import patch

        import os

        from services.validemail_keys import max_domains_per_seller, validation_wall_sec

        with patch.dict(
            os.environ,
            {
                "VALIDEMAIL_MAX_DOMAINS_PROBE": "",
                "VALIDEMAIL_DEADLINE_SEC": "",
                "VALIDEMAIL_URL": "https://validemail.co/api/v1/validate",
                "VALIDEMAIL_MAILCHECK": "0",
            },
            clear=False,
        ):
            self.assertEqual(max_domains_per_seller(), 0)
            self.assertEqual(validation_wall_sec(7), 0.0)
        with patch.dict(
            os.environ,
            {
                "VALIDEMAIL_DEADLINE_SEC": "",
                "VALIDEMAIL_URL": "https://validator-production-7106.up.railway.app/api/v1/validate",
                "VALIDEMAIL_MAILCHECK": "",
            },
            clear=False,
        ):
            self.assertEqual(validation_wall_sec(1), 300.0)
        with patch.dict(os.environ, {"VALIDEMAIL_DEADLINE_SEC": "300"}, clear=False):
            self.assertEqual(validation_wall_sec(1), 300.0)
        with patch.dict(os.environ, {"VALIDEMAIL_DEADLINE_SEC": "90"}, clear=False):
            self.assertEqual(validation_wall_sec(1), 90.0)
        with patch.dict(os.environ, {"VALIDEMAIL_MAX_DOMAINS_PROBE": "0"}, clear=False):
            self.assertEqual(max_domains_per_seller(), 0)

    def test_seven_keys_scale_as_keys_times_per_key(self):
        from unittest.mock import patch

        import os

        from services.validemail_keys import (
            global_inflight_cap,
            per_key_concurrency_limit,
            seller_parallel_per_key,
        )

        ve = {
            "VALIDEMAIL_URL": "https://validemail.co/api/v1/validate",
            "VALIDEMAIL_MAILCHECK": "0",
            "VALIDEMAIL_CONCURRENCY_PER_KEY": "",
            "VALIDEMAIL_GLOBAL_INFLIGHT": "200",
            "VALIDEMAIL_SELLER_PARALLEL_PER_KEY": "",
        }
        with patch.dict(os.environ, ve, clear=False):
            self.assertEqual(per_key_concurrency_limit(), 10)
            self.assertEqual(seller_parallel_per_key(), 10)
            self.assertEqual(global_inflight_cap(7), 70)
        with patch.dict(os.environ, {**ve, "VALIDEMAIL_CONCURRENCY_PER_KEY": "7"}, clear=False):
            self.assertEqual(per_key_concurrency_limit(), 7)
            self.assertEqual(global_inflight_cap(7), 49)
        with patch.dict(os.environ, {**ve, "VALIDEMAIL_CONCURRENCY_PER_KEY": "22"}, clear=False):
            self.assertEqual(per_key_concurrency_limit(), 10)

        mc = {
            "VALIDEMAIL_URL": "https://validator-production-7106.up.railway.app/api/v1/validate",
            "VALIDEMAIL_MAILCHECK": "",
            "VALIDEMAIL_CONCURRENCY_PER_KEY": "",
            "VALIDEMAIL_SELLER_PARALLEL_PER_KEY": "",
        }
        with patch.dict(os.environ, mc, clear=False):
            self.assertEqual(per_key_concurrency_limit(), 40)
            self.assertEqual(seller_parallel_per_key(), 24)
            self.assertEqual(global_inflight_cap(1), 40)
        with patch.dict(os.environ, {**mc, "VALIDEMAIL_CONCURRENCY_PER_KEY": "48"}, clear=False):
            self.assertEqual(per_key_concurrency_limit(), 48)

    def test_unknown_domain_cap_default(self):
        from unittest.mock import patch

        import os

        from services.validemail_keys import max_unknown_domains_per_seller
        from services.validemail_fast import _validemail_api_timeout

        with patch.dict(
            os.environ,
            {
                "VALIDEMAIL_MAX_UNKNOWN_DOMAINS": "",
                "VALIDEMAIL_API_TIMEOUT": "",
                "VALIDEMAIL_URL": "https://validemail.co/api/v1/validate",
                "VALIDEMAIL_MAILCHECK": "0",
            },
            clear=False,
        ):
            self.assertEqual(max_unknown_domains_per_seller(), 4)
            self.assertEqual(_validemail_api_timeout(), 4)
        with patch.dict(
            os.environ,
            {
                "VALIDEMAIL_API_TIMEOUT": "",
                "VALIDEMAIL_URL": "https://validator-production-7106.up.railway.app/api/v1/validate",
                "VALIDEMAIL_MAILCHECK": "",
            },
            clear=False,
        ):
            self.assertEqual(_validemail_api_timeout(), 8)
        with patch.dict(
            os.environ,
            {"VALIDEMAIL_API_TIMEOUT": "12", "VALIDEMAIL_MAILCHECK": "0"},
            clear=False,
        ):
            self.assertEqual(_validemail_api_timeout(), 8)

    def test_gmx_mailbox_helper(self):
        from services.validemail_fast import _is_gmx_mailbox, _is_soft_smtp_domain

        self.assertTrue(_is_gmx_mailbox("max@gmx.de"))
        self.assertTrue(_is_gmx_mailbox("max@web.de"))
        self.assertFalse(_is_gmx_mailbox("max@gmail.com"))
        self.assertTrue(_is_soft_smtp_domain("bluewin.ch"))
        self.assertTrue(_is_soft_smtp_domain("a@sunrise.ch"))
        self.assertTrue(_is_soft_smtp_domain("x@gmx.ch"))
        self.assertFalse(_is_soft_smtp_domain("gmail.com"))

    def test_gmx_policy_pause_not_permanent(self):
        from services.validemail_fast import (
            _GMX_MX_DEAD,
            _GMX_PAUSE_UNTIL,
            _gmx_note_result,
            gmx_mx_dead,
            reset_validemail_runtime,
        )
        import services.validemail_fast as vf

        reset_validemail_runtime()
        self.assertFalse(gmx_mx_dead())
        _gmx_note_result(
            {"reason": "connection_error", "detail": "421-gmx.net Reject due to policy restrictions."}
        )
        self.assertTrue(gmx_mx_dead())
        vf._GMX_PAUSE_UNTIL = 0.0
        self.assertFalse(gmx_mx_dead())
        self.assertFalse(vf._GMX_MX_DEAD)

    def test_gmx_pacing_spreads_large_batch_over_two_minutes(self):
        from services.validemail_fast import (
            _gmx_policy_blocked,
            configure_gmx_pacing,
            reset_validemail_runtime,
        )

        reset_validemail_runtime()
        gap = configure_gmx_pacing([f"u{i}@gmx.de" for i in range(80)])
        self.assertGreaterEqual(gap, 0.35)
        self.assertLessEqual(gap, 0.8)
        self.assertLessEqual(gap * 80, 180.0)
        small = configure_gmx_pacing(["a@gmx.de", "b@web.de"])
        self.assertLessEqual(small, 0.4)
        self.assertTrue(
            _gmx_policy_blocked(
                {
                    "reason": "connection_error",
                    "detail": "421-gmx.net Reject due to policy restrictions.",
                }
            )
        )
        self.assertFalse(_gmx_policy_blocked({"reason": "rejected", "detail": "550"}))


if __name__ == "__main__":
    unittest.main()
