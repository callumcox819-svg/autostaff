"""GAG снова в Команды API."""
from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from services.api_teams import API_TEAMS, default_service_for_team, normalize_team_id


class ApiTeamsGagTests(unittest.TestCase):
    def test_gag_in_list(self):
        ids = {tid for tid, _ in API_TEAMS}
        self.assertIn("gag", ids)
        self.assertEqual(normalize_team_id("gag"), "gag")
        self.assertEqual(normalize_team_id("aqua"), "gag")

    def test_gag_default_service_is_swiss_ricardo(self):
        self.assertEqual(default_service_for_team("gag"), "ricardo_ch")

    def test_gag_link_versions_match_api_documentation(self):
        from services.api_teams import link_types_for_team

        self.assertEqual(
            [code for code, _, _ in link_types_for_team("gag")],
            ["lk", "1", "2"],
        )

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
        self.assertIn("Ricardo", text)
        self.assertIn("ricardo_ch", text)
        self.assertNotIn("GENERATE_API_BASE", text)
        self.assertNotIn("marktplaats", text)
        self.assertNotIn("kleinanzeigen", text)

        callbacks = {
            button.callback_data
            for row in _team_detail_kb("gag", service_code="ricardo_ch").inline_keyboard
            for button in row
        }
        self.assertIn("api_team_gag_svc:gag:ricardo_ch", callbacks)
        self.assertIn("api_team_gag_svc:gag:markt_ch", callbacks)
        self.assertNotIn("api_team_edit:gag:service_code", callbacks)
        labels = [
            button.text
            for row in _team_detail_kb("gag", service_code="ricardo_ch").inline_keyboard
            for button in row
        ]
        self.assertTrue(any("Markt.ch" in (t or "") for t in labels))
        self.assertTrue(any("Ricardo" in (t or "") for t in labels))


class ApiTeamsGagAsyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_gag_service_cannot_be_changed(self):
        from services.api_teams import set_team_field

        with self.assertRaisesRegex(ValueError, "Markt.ch"):
            await set_team_field(
                AsyncMock(),
                SimpleNamespace(id=1),
                "gag",
                "service_code",
                "marktplaats_nl",
            )

    async def test_gag_can_select_markt_ch(self):
        from services.api_teams import set_team_field

        session = AsyncMock()
        user = SimpleNamespace(id=1)
        with (
            patch("services.country_scope.set_scoped_setting", new=AsyncMock()) as write,
        ):
            await set_team_field(session, user, "gag", "service_code", "markt.ch")
        write.assert_awaited()
        self.assertEqual(write.await_args.args[3], "markt_ch")


if __name__ == "__main__":
    unittest.main()
