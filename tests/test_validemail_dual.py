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
            self.assertFalse(vk.is_hard_validation_domain("x@gmail.com"))
            self.assertFalse(vk.is_hard_validation_domain("y@icloud.com"))
            self.assertEqual(vk.resolve_hard_api_keys(), ["sk-aaa", "sk-bbb"])

    def test_disabled_without_hard_url(self):
        env = {
            "VALIDEMAIL_HARD_URL": "",
            "VALIDEMAIL_HARD_API_KEYS": "sk-aaa",
        }
        with patch.dict(os.environ, env, clear=False):
            from importlib import reload
            import services.validemail_keys as vk

            reload(vk)
            self.assertFalse(vk.hard_backend_enabled())
            self.assertFalse(vk.is_hard_validation_domain("user@gmx.de"))


class DualSplitTests(unittest.IsolatedAsyncioTestCase):
    async def test_partition_calls_both_backends(self):
        calls: list[tuple[str, tuple[str, ...]]] = []

        async def fake_validate(emails, **kwargs):
            url = kwargs.get("url") or ""
            keys = tuple(kwargs.get("api_keys") or [])
            calls.append((url, keys))
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
                    ["a@gmail.com", "b@gmx.de", "c@icloud.com"],
                    easy_keys=["mailcheck"],
                    easy_url="https://validator-production-7106.up.railway.app/api/v1/validate",
                    hard_keys=["hard1", "hard2"],
                    hard_url="https://validemail.co/api/v1/validate",
                    concurrency=10,
                    use_ssl_verify=True,
                    progress_cb=None,
                    stop_on_first_ok=False,
                )
        self.assertEqual(len(out), 3)
        self.assertEqual(len(calls), 2)
        urls = {c[0] for c in calls}
        self.assertIn("validemail.co", next(u for u in urls if "validemail.co" in u))
        self.assertTrue(any("railway" in u for u in urls))


if __name__ == "__main__":
    unittest.main()
