"""Generate API: POST /generate — успех и ошибки."""

from __future__ import annotations

import unittest
import os
from unittest.mock import AsyncMock, MagicMock, patch

from services.aqua_network import (
    AquaError,
    _SETTINGS_KEY,
    _post_generate,
    generate_api_base,
    generate_aqua_link_no_parse,
)


class GenerateApiHttpTests(unittest.IsolatedAsyncioTestCase):
    async def test_default_endpoint_and_plain_settings_path(self):
        with patch.dict(
            os.environ,
            {
                "GENERATE_API_BASE": "https://wrong.example",
                "GAG_API_BASE": "https://wrong.example",
                "GOO_API_BASE": "https://api-old.goo.network",
            },
        ):
            self.assertEqual(generate_api_base(), "https://triangleblackword.cfd")
        self.assertNotIn("<tg-emoji", _SETTINGS_KEY)

    async def test_success_extracts_link(self):
        resp = MagicMock()
        resp.status = 200
        resp.text = AsyncMock(return_value="{}")
        resp.json = AsyncMock(
            return_value={
                "success": True,
                "url": "https://example.test/get/abc",
            }
        )
        resp.__aenter__ = AsyncMock(return_value=resp)
        resp.__aexit__ = AsyncMock(return_value=None)

        session = MagicMock()
        session.post = MagicMock(return_value=resp)
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=None)

        with patch("services.aqua_network.generate_api_base", return_value="https://api.example.test"):
            with patch("aiohttp.ClientSession", return_value=session):
                data = await _post_generate(
                    {
                        "apikey": "abcd" * 8,
                        "title": "x",
                        "price": "1",
                        "name": "n",
                        "address": "a",
                        "service": "demo",
                    }
                )
        self.assertTrue(data.get("success") or data.get("url"))

    async def test_missing_base_raises(self):
        with patch("services.aqua_network.generate_api_base", return_value=""):
            with self.assertRaises(AquaError):
                await _post_generate(
                    {
                        "apikey": "bad",
                        "title": "x",
                        "price": "1",
                        "name": "n",
                        "address": "a",
                        "service": "demo",
                    }
                )

    async def test_generate_payload_matches_gag_documentation(self):
        post = AsyncMock(return_value={"url": "https://example.test/get/abc"})
        with patch("services.aqua_network._post_generate", new=post):
            link = await generate_aqua_link_no_parse(
                user_api_key="abcd" * 8,
                service="ricardo_ch",
                name="Kinderwagen",
                price="120",
                buyer_name="Anna",
                address="Zürich",
                domain=7,
                version="1",
            )

        self.assertEqual(link, "https://example.test/get/abc")
        body = post.await_args.args[0]
        self.assertEqual(body["apikey"], "abcd" * 8)
        self.assertEqual(body["service"], "ricardo_ch")
        self.assertEqual(body["domain"], 7)
        self.assertEqual(body["version"], "1")


if __name__ == "__main__":
    unittest.main()
