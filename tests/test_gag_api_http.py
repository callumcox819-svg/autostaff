"""Generate API: POST /generate — успех и ошибки."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from services.aqua_network import AquaError, _post_generate


class GenerateApiHttpTests(unittest.IsolatedAsyncioTestCase):
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


if __name__ == "__main__":
    unittest.main()
