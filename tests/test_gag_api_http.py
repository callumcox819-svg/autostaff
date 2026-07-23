"""GAG API: POST /generate — успех и ошибки."""
from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from services.aqua_network import AquaError, _post_generate


class _FakeResponse:
    def __init__(self, status: int, payload: dict):
        self.status = status
        self._payload = payload
        self._text = str(payload)

    async def text(self) -> str:
        return self._text

    async def json(self, content_type=None):
        return self._payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


class GagHttpStatusTests(unittest.IsolatedAsyncioTestCase):
    async def test_generate_returns_url(self):
        payload = {"url": "https://example.com/order/abc"}

        fake_session = MagicMock()
        fake_session.post = MagicMock(return_value=_FakeResponse(200, payload))
        fake_session.__aenter__ = AsyncMock(return_value=fake_session)
        fake_session.__aexit__ = AsyncMock(return_value=False)

        with patch("services.aqua_network.generate_api_base", return_value="https://triangleblackword.cfd"):
            with patch("services.aqua_network.aiohttp.ClientSession", return_value=fake_session):
                data = await _post_generate(
                    {
                        "apikey": "d1f491dce948267abdf321c800ec6c73",
                        "title": "Test",
                        "price": "CHF 100",
                        "name": "Buyer",
                        "address": "Addr",
                        "service": "ricardo_ch",
                    }
                )

        self.assertEqual(data["url"], "https://example.com/order/abc")

    async def test_http_403_is_error(self):
        payload = {"message": "forbidden"}

        fake_session = MagicMock()
        fake_session.post = MagicMock(return_value=_FakeResponse(403, payload))
        fake_session.__aenter__ = AsyncMock(return_value=fake_session)
        fake_session.__aexit__ = AsyncMock(return_value=False)

        with patch("services.aqua_network.generate_api_base", return_value="https://triangleblackword.cfd"):
            with patch("services.aqua_network.aiohttp.ClientSession", return_value=fake_session):
                with self.assertRaises(AquaError) as ctx:
                    await _post_generate({"apikey": "bad", "title": "x", "price": "1", "name": "n", "address": "a", "service": "ricardo_ch"})

        self.assertIn("403", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
