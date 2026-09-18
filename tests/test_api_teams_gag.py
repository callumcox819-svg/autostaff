"""GAG снова в Команды API."""
from __future__ import annotations

import unittest

from services.api_teams import API_TEAMS, default_service_for_team, normalize_team_id
from services.country_scope import force_germany_ebay_service


class ApiTeamsGagTests(unittest.TestCase):
    def test_gag_in_list(self):
        ids = {tid for tid, _ in API_TEAMS}
        self.assertIn("gag", ids)
        self.assertEqual(normalize_team_id("gag"), "gag")
        self.assertEqual(normalize_team_id("aqua"), "gag")

    def test_gag_keeps_service_on_germany(self):
        self.assertEqual(
            force_germany_ebay_service("gag", "marktplaats_nl"),
            "marktplaats_nl",
        )
        self.assertTrue(default_service_for_team("gag"))


if __name__ == "__main__":
    unittest.main()
