# -*- coding: utf-8 -*-
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from services.api_teams import default_service_for_team, normalize_team_id
from services.bastard_catalog import (
    BASTARD_DEFAULT_SERVICE,
    bastard_generate_mode,
    bastard_service_label,
    parse_bastard_service,
    platforms_for_bastard_country,
)


class BastardCatalogTests(unittest.TestCase):
    def test_hungary_jofogas_fast(self):
        ids = [sid for sid, _, _, _ in platforms_for_bastard_country("hu")]
        self.assertIn("jofogas_hu", ids)
        self.assertEqual(BASTARD_DEFAULT_SERVICE, "jofogas_hu")
        self.assertEqual(bastard_generate_mode("jofogas_hu"), "fast")
        self.assertEqual(bastard_generate_mode("facebook_hu"), "lonely")
        self.assertIn("Jófogás", bastard_service_label("jofogas_hu"))
        self.assertEqual(parse_bastard_service("jofogas_hu"), ("jofogas_hu", "hu"))
        self.assertEqual(normalize_team_id("bastard"), "bastard")
        self.assertEqual(normalize_team_id("bastard_team"), "bastard")
        self.assertEqual(default_service_for_team("bastard"), "jofogas_hu")


class BastardGenerateTests(unittest.IsolatedAsyncioTestCase):
    async def test_jofogas_with_price_uses_fast_not_lonely(self):
        from services.aqua_link import _generate_hustle

        cfg = SimpleNamespace(
            api_key="user-key",
            team_key="team-key",
            service_code="jofogas_hu",
            profile_id="prof1",
            link_type="lk",
            team_id="bastard",
            label="BASTARD",
        )
        offer = SimpleNamespace(
            title="Kerékpár",
            price="155000",
            link="https://www.jofogas.hu/budapest/x",
            item_link="https://www.jofogas.hu/budapest/x",
            photo="https://img.example/a.jpg",
            raw_json=None,
        )
        user = SimpleNamespace(id=1)
        fast = AsyncMock(return_value="https://ok.example/fast")
        lonely = AsyncMock(return_value="https://ok.example/lonely")
        with (
            patch("services.aqua_link.hustle_generate_fast", fast),
            patch("services.aqua_link.hustle_generate_lonely", lonely),
            patch(
                "services.api_teams.get_team_field",
                new=AsyncMock(return_value="Budapest"),
            ),
            patch(
                "services.aqua_link.resolve_aqua_image_url",
                new=AsyncMock(return_value="https://img.example/a.jpg"),
            ),
        ):
            link = await _generate_hustle(
                None,
                user,
                cfg,
                offer,
                listing_url=offer.link,
                price="155 000 Ft",
            )
        self.assertEqual(link, "https://ok.example/fast")
        fast.assert_awaited_once()
        lonely.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
