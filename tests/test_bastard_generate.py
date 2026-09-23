# -*- coding: utf-8 -*-
import unittest

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


if __name__ == "__main__":
    unittest.main()
