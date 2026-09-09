# -*- coding: utf-8 -*-
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from services.goo_network import GooError, goo_generate_no_parse, goo_generate_parse


class GooGenerateTests(unittest.IsolatedAsyncioTestCase):
    async def test_no_parse_ok(self):
        resp = MagicMock()
        resp.status = 200
        resp.text = AsyncMock(return_value="{}")
        resp.json = AsyncMock(
            return_value={"status": True, "message": "https://mp.example/get/1"}
        )
        resp.__aenter__ = AsyncMock(return_value=resp)
        resp.__aexit__ = AsyncMock(return_value=None)
        session = MagicMock()
        session.post = MagicMock(return_value=resp)
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=None)

        with patch("aiohttp.ClientSession", return_value=session):
            link = await goo_generate_no_parse(
                user_api_key="user-key",
                team_api_key="team-key",
                service="marktplaats_nl",
                name="Bike",
                price="100",
                profile_id="gA0XGRof08x",
                image="https://img.example/a.jpg",
            )
        self.assertEqual(link, "https://mp.example/get/1")
        _args, kwargs = session.post.call_args
        self.assertIn("/api/generate/single/no-parse", _args[0])
        self.assertEqual(kwargs["headers"]["Authorization"], "Apikey user-key")
        self.assertEqual(kwargs["headers"]["X-Team-Key"], "team-key")
        self.assertEqual(kwargs["json"]["service"], "marktplaats_nl")
        self.assertEqual(kwargs["json"]["profileID"], "gA0XGRof08x")

    async def test_parse_requires_url(self):
        with self.assertRaises(GooError):
            await goo_generate_parse(
                user_api_key="k",
                service="marktplaats_nl",
                listing_url="",
                profile_id="p",
            )


if __name__ == "__main__":
    unittest.main()
