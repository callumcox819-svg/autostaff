# -*- coding: utf-8 -*-
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from services.api_teams import normalize_team_id
from services.hustle_catalog import (
    hustle_generate_mode,
    hustle_service_label,
    parse_hustle_service,
    platforms_for_hustle_country,
)
from services.hustle_network import extract_hustle_link, hustle_generate_fast, hustle_generate_custom


class HustleCatalogTests(unittest.TestCase):
    def test_germany_has_kleinanzeigen_and_ebay(self):
        ids = [sid for sid, _, _, _ in platforms_for_hustle_country("de")]
        self.assertIn("kleinanzeigen_de", ids)
        self.assertIn("ebay_de", ids)
        self.assertEqual(hustle_generate_mode("kleinanzeigen_de"), "fast")
        self.assertEqual(hustle_generate_mode("ebay_de"), "custom")
        self.assertIn("eBay", hustle_service_label("ebay_de"))
        self.assertEqual(parse_hustle_service("kleinanzeigen_de"), ("kleinanzeigen_de", "de"))
        self.assertEqual(normalize_team_id("hustle_castle"), "hustle")
        self.assertEqual(normalize_team_id("bastard"), "bastard")
        self.assertEqual(normalize_team_id("evoleum"), "evoleum")
        self.assertEqual(normalize_team_id("csm"), "csm")


class HustleGenerateTests(unittest.IsolatedAsyncioTestCase):
    def test_extract_link_prefers_lk(self):
        data = {
            "status": True,
            "Link": "https://a.example/full",
            "Link_shortener": "https://a.example/s",
            "Link_multi": "https://a.example/m",
        }
        self.assertEqual(extract_hustle_link(data, link_type="lk"), "https://a.example/full")
        self.assertEqual(extract_hustle_link(data, link_type="card"), "https://a.example/s")
        self.assertEqual(extract_hustle_link(data, link_type="other"), "https://a.example/m")

    async def test_fast_headers_and_body(self):
        resp = MagicMock()
        resp.status = 200
        resp.text = AsyncMock(return_value="{}")
        resp.json = AsyncMock(return_value={"status": True, "Link": "https://ok.example/x"})
        resp.__aenter__ = AsyncMock(return_value=resp)
        resp.__aexit__ = AsyncMock(return_value=None)
        session = MagicMock()
        session.post = MagicMock(return_value=resp)
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=None)

        with patch("services.hustle_network._wait_rate_limit", new=AsyncMock()), patch(
            "aiohttp.ClientSession", return_value=session
        ):
            link = await hustle_generate_fast(
                api_key="user-key",
                team_key="team-key",
                service="kleinanzeigen_de",
                listing_url="https://www.kleinanzeigen.de/s-anzeige/1",
                profile_id="osQZ9NLWq",
            )
        self.assertEqual(link, "https://ok.example/x")
        args, kwargs = session.post.call_args
        self.assertIn("/api/order/generate/fast", args[0])
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer user-key")
        self.assertEqual(kwargs["headers"]["X-Team-Key"], "team-key")
        self.assertEqual(kwargs["json"]["service"], "kleinanzeigen_de")
        self.assertEqual(kwargs["json"]["profileId"], "osQZ9NLWq")
        self.assertTrue(str(kwargs["json"]["linkAt"]).startswith("www.kleinanzeigen.de"))

    async def test_custom_ebay_uses_customservice_de(self):
        resp = MagicMock()
        resp.status = 200
        resp.text = AsyncMock(return_value="{}")
        resp.json = AsyncMock(return_value={"status": True, "Link": "https://ok.example/ebay"})
        resp.__aenter__ = AsyncMock(return_value=resp)
        resp.__aexit__ = AsyncMock(return_value=None)
        session = MagicMock()
        session.post = MagicMock(return_value=resp)
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=None)

        with patch("services.hustle_network._wait_rate_limit", new=AsyncMock()), patch(
            "aiohttp.ClientSession", return_value=session
        ):
            link = await hustle_generate_custom(
                api_key="u",
                team_key="t",
                name="iPhone",
                price="100",
                user="Niklas Meyer",
                address="Berliner Straße 1, 10115 Berlin",
                photo="https://img.example/a.jpg",
            )
        self.assertEqual(link, "https://ok.example/ebay")
        _args, kwargs = session.post.call_args
        self.assertIn("/api/order/generate/custom", _args[0])
        self.assertEqual(kwargs["json"]["service"], "customservice_de")
        self.assertEqual(kwargs["json"]["platformName"], "eBay")
        self.assertEqual(kwargs["json"]["platformCountry"], "de")
        self.assertEqual(kwargs["json"]["price"], 100.0)


if __name__ == "__main__":
    unittest.main()
