"""Narkologia API: HTTP 2xx (в т.ч. 201 Created) — успех, не ошибка."""
from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from services.aqua_network import AquaError, _request_json


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


class NarkologiaHttpStatusTests(unittest.IsolatedAsyncioTestCase):
    async def test_http_201_order_created_is_success(self):
        payload = {
            "success": True,
            "message": "Order created",
            "details": {"short": {"url": "https://example.com/order/abc"}},
        }

        fake_session = MagicMock()
        fake_session.request = MagicMock(
            return_value=_FakeResponse(201, payload)
        )
        fake_session.__aenter__ = AsyncMock(return_value=fake_session)
        fake_session.__aexit__ = AsyncMock(return_value=False)

        with patch("services.aqua_network.aiohttp.ClientSession", return_value=fake_session):
            data = await _request_json(
                "POST",
                "/api/order/generate/lonely",
                user_api_key="user-token",
                team_api_key="team-token",
                body={"service": "2dehands_be"},
            )

        self.assertEqual(data["message"], "Order created")

    async def test_http_500_is_error(self):
        payload = {"message": "server error"}

        fake_session = MagicMock()
        fake_session.request = MagicMock(
            return_value=_FakeResponse(500, payload)
        )
        fake_session.__aenter__ = AsyncMock(return_value=fake_session)
        fake_session.__aexit__ = AsyncMock(return_value=False)

        with patch("services.aqua_network.aiohttp.ClientSession", return_value=fake_session):
            with self.assertRaises(AquaError) as ctx:
                await _request_json(
                    "POST",
                    "/api/order/generate/lonely",
                    user_api_key="user-token",
                    team_api_key="team-token",
                    body={},
                )

        self.assertIn("HTTP 500", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
