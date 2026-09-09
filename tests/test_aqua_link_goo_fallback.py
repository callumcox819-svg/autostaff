# -*- coding: utf-8 -*-
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from services.aqua_link import _generate_goo
from services.goo_network import GooError


class GooParseFallbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_parse_fail_falls_back_to_no_parse(self):
        cfg = SimpleNamespace(
            label="Evoleum",
            api_key="user-key",
            team_key="team-key",
            profile_id="pid",
            service_code="marktplaats_nl",
        )
        offer = SimpleNamespace(
            title="Bike",
            price="100",
            photo="https://img.example/a.jpg",
            link="https://www.marktplaats.nl/v/bad",
            item_link=None,
        )
        user = SimpleNamespace(id=1)

        with (
            patch(
                "services.aqua_link.goo_generate_parse",
                new=AsyncMock(side_effect=GooError("HTTP 500: cant validate link for parsing")),
            ),
            patch(
                "services.aqua_link.goo_generate_no_parse",
                new=AsyncMock(return_value="https://ok.example/x"),
            ) as no_parse,
            patch(
                "services.aqua_link.resolve_aqua_image_url",
                new=AsyncMock(return_value="https://img.example/a.jpg"),
            ),
            patch("services.aqua_link.offer_effective_title", return_value="Bike"),
            patch("services.aqua_link.offer_effective_price", return_value="100"),
        ):
            link = await _generate_goo(None, user, cfg, offer, listing_url=None, price=None)

        self.assertEqual(link, "https://ok.example/x")
        no_parse.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
