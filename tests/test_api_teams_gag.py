"""GAG снова в Команды API."""
from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from services.api_teams import API_TEAMS, default_service_for_team, normalize_team_id


class ApiTeamsGagTests(unittest.TestCase):
    def test_gag_in_list(self):
        ids = {tid for tid, _ in API_TEAMS}
        self.assertIn("gag", ids)
        self.assertEqual(normalize_team_id("gag"), "gag")
        self.assertEqual(normalize_team_id("aqua"), "gag")

    def test_gag_service_is_fixed_to_swiss_ricardo(self):
        self.assertEqual(default_service_for_team("gag"), "ricardo_ch")

    def test_gag_ui_hides_internal_server_config_and_foreign_services(self):
        from handlers.api_teams import _team_detail_kb, _team_detail_text

        cfg = SimpleNamespace(
            team_id="gag",
            label="GAG",
            api_key="abcdef1234567890",
            service_code="ricardo_ch",
            profile_id="",
            link_type="lk",
        )
        text = _team_detail_text(
            cfg,
            buyer_name="Anna",
            address="Zürich",
            country_name="Швейцария",
        )
        self.assertIn("Ricardo Switzerland", text)
        self.assertNotIn("GENERATE_API_BASE", text)
        self.assertNotIn("marktplaats", text)
        self.assertNotIn("kleinanzeigen", text)

        callbacks = {
            button.callback_data
            for row in _team_detail_kb("gag").inline_keyboard
            for button in row
        }
        self.assertNotIn("api_team_edit:gag:service_code", callbacks)


class ApiTeamsGagAsyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_gag_service_cannot_be_changed(self):
        from services.api_teams import set_team_field

        with self.assertRaisesRegex(ValueError, "Ricardo Switzerland"):
            await set_team_field(
                AsyncMock(),
                SimpleNamespace(id=1),
                "gag",
                "service_code",
                "marktplaats_nl",
            )


if __name__ == "__main__":
    unittest.main()
