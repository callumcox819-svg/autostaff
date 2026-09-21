import os
import unittest
from unittest.mock import patch


class HardValidationRoutingTests(unittest.TestCase):
    def test_hard_domains_when_backend_enabled(self):
        env = {
            "VALIDEMAIL_HARD_URL": "https://validemail.co/api/v1/validate",
            "VALIDEMAIL_HARD_API_KEYS": "sk-aaa,sk-bbb",
            "VALIDEMAIL_URL": "https://validator-production-7106.up.railway.app/api/v1/validate",
        }
        with patch.dict(os.environ, env, clear=False):
            from importlib import reload
            import services.validemail_keys as vk

            reload(vk)
            self.assertTrue(vk.hard_backend_enabled())
            self.assertTrue(vk.is_hard_validation_domain("user@gmx.de"))
            self.assertTrue(vk.is_hard_validation_domain("a@bluewin.ch"))
            self.assertTrue(vk.is_hard_validation_domain("b@sunrise.ch"))
            self.assertTrue(vk.is_hard_validation_domain("c@web.de"))
            self.assertTrue(vk.is_hard_validation_domain("x@kpnmail.nl"))
            self.assertTrue(vk.is_hard_validation_domain("y@gmx.at"))
            self.assertTrue(vk.is_hard_validation_domain("z@hotmail.com"))
            self.assertFalse(vk.is_hard_validation_domain("x@gmail.com"))
            self.assertFalse(vk.is_hard_validation_domain("y@icloud.com"))
            self.assertFalse(vk.is_hard_validation_domain("z@me.com"))
            self.assertEqual(vk.resolve_hard_api_keys(), ["sk-aaa", "sk-bbb"])

    def test_eight_bot_keys_enable_dual_without_hard_url(self):
        eight = ",".join(f"ve-key-{i}" for i in range(8))
        env = {
            "VALIDEMAIL_HARD_URL": "",
            "VALIDEMAIL_HARD_API_KEYS": "",
            "VALIDEMAIL_API_KEYS": eight,
            "VALIDEMAIL_URL": "https://validator-production-7106.up.railway.app/api/v1/validate",
        }
        with patch.dict(os.environ, env, clear=False):
            from importlib import reload
            import config as cfg
            import services.validemail_keys as vk

            reload(cfg)
            reload(vk)
            self.assertEqual(len(vk.resolve_hard_api_keys()), 8)
            self.assertTrue(vk.hard_backend_enabled())
            self.assertIn("validemail.co", vk.hard_validation_url())
            self.assertTrue(vk.is_hard_validation_domain("a@gmx.ch"))
            self.assertTrue(vk.is_hard_validation_domain("b@bluewin.ch"))
            self.assertTrue(vk.is_hard_validation_domain("c@sunrise.ch"))
            self.assertFalse(vk.is_hard_validation_domain("x@gmail.com"))
            self.assertEqual(vk.resolve_validemail_api_keys(), ["mailcheck"])

    def test_co_url_still_sends_gmail_to_mailcheck(self):
        eight = ",".join(f"ve-key-{i}" for i in range(8))
        env = {
            "VALIDEMAIL_HARD_URL": "",
            "VALIDEMAIL_HARD_API_KEYS": "",
            "VALIDEMAIL_API_KEYS": eight,
            "VALIDEMAIL_URL": "https://validemail.co/api/v1/validate",
        }
        with patch.dict(os.environ, env, clear=False):
            from importlib import reload
            import config as cfg
            import services.validemail_keys as vk

            reload(cfg)
            reload(vk)
            self.assertTrue(vk.hard_backend_enabled())
            self.assertEqual(vk.resolve_validemail_api_keys(), ["mailcheck"])
            self.assertFalse(vk.is_hard_validation_domain("x@gmail.com"))
            self.assertTrue(vk.is_hard_validation_domain("a@gmx.ch"))

    def test_disabled_without_hard_url_or_real_keys(self):
        env = {
            "VALIDEMAIL_HARD_URL": "",
            "VALIDEMAIL_HARD_API_KEYS": "",
            "VALIDEMAIL_API_KEYS": "mailcheck",
        }
        with patch.dict(os.environ, env, clear=False):
            from importlib import reload
            import config as cfg
            import services.validemail_keys as vk

            reload(cfg)
            reload(vk)
            self.assertFalse(vk.hard_backend_enabled())
            self.assertFalse(vk.is_hard_validation_domain("user@gmx.de"))


class DualSplitTests(unittest.IsolatedAsyncioTestCase):
    async def test_partition_calls_both_backends(self):
        calls: list[tuple[str, tuple[str, ...]]] = []

        async def fake_validate(emails, **kwargs):
            url = kwargs.get("url") or ""
            keys = tuple(kwargs.get("api_keys") or [])
            calls.append((url, keys, tuple(emails)))
            return [(e, True, {"ok": True}) for e in emails]

        env = {
            "VALIDEMAIL_HARD_URL": "https://validemail.co/api/v1/validate",
            "VALIDEMAIL_HARD_API_KEYS": "hard1,hard2",
            "VALIDEMAIL_URL": "https://validator-production-7106.up.railway.app/api/v1/validate",
            "VALIDEMAIL_API_KEYS": "mailcheck",
        }
        with patch.dict(os.environ, env, clear=False):
            from importlib import reload
            import services.validemail_keys as vk
            import services.validemail_fast as vf

            reload(vk)
            reload(vf)
            with patch.object(vf, "validate_emails_fast", side_effect=fake_validate):
                # Call partitioned helper directly to avoid recursion through patched name.
                out = await vf._validate_emails_partitioned(
                    [
                        "a@gmail.com",
                        "b@gmx.ch",
                        "c@icloud.com",
                        "d@sunrise.ch",
                        "e@bluewin.ch",
                    ],
                    easy_keys=["mailcheck"],
                    easy_url="https://validator-production-7106.up.railway.app/api/v1/validate",
                    hard_keys=["hard1", "hard2"],
                    hard_url="https://validemail.co/api/v1/validate",
                    concurrency=10,
                    use_ssl_verify=True,
                    progress_cb=None,
                    stop_on_first_ok=False,
                )
        self.assertEqual(len(out), 5)
        self.assertEqual(len(calls), 2)
        by_url = {c[0]: c for c in calls}
        co_url = next(u for u in by_url if "validemail.co" in u)
        rail_url = next(u for u in by_url if "railway" in u)
        self.assertEqual(by_url[co_url][1], ("hard1", "hard2"))
        self.assertEqual(by_url[rail_url][1], ("mailcheck",))
        self.assertEqual(set(by_url[co_url][2]), {"b@gmx.ch", "d@sunrise.ch", "e@bluewin.ch"})
        self.assertEqual(set(by_url[rail_url][2]), {"a@gmail.com", "c@icloud.com"})


class DualSpeedPlanTests(unittest.TestCase):
    def test_eight_hard_keys_raise_seller_cap(self):
        env = {
            "VALIDEMAIL_HARD_URL": "https://validemail.co/api/v1/validate",
            "VALIDEMAIL_HARD_API_KEYS": ",".join(f"k{i}" for i in range(8)),
            "VALIDEMAIL_URL": "https://validator-production-7106.up.railway.app/api/v1/validate",
        }
        with patch.dict(os.environ, env, clear=False):
            from importlib import reload
            import services.validemail_keys as vk

            reload(vk)
            cap = vk.seller_parallel_cap_for_run(1, 8)
            self.assertGreaterEqual(cap, 80)
            self.assertEqual(vk.per_key_concurrency_limit(vk.hard_validation_url()) * 8, 80)


if __name__ == "__main__":
    unittest.main()
