"""HTML routing: сервисы из AQUA_SERVICES, шаблоны в data/HTML/."""

from __future__ import annotations

import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch


class AquaHtmlRoutingTests(unittest.TestCase):
    def test_swiss_services_from_html_dirs(self):
        with patch.dict(os.environ, {"AQUA_SERVICES": "", "HTML_DATA_DIR": "HTML"}, clear=False):
            import importlib
            import services.aqua_keys as ak
            import region as region_mod

            importlib.reload(region_mod)
            importlib.reload(ak)
            self.assertEqual(ak.normalize_aqua_service("ricardo_ch"), "ricardo_ch")
            self.assertEqual(ak.normalize_aqua_service("tutti_ch"), "tutti_ch")
            self.assertEqual(ak.normalize_aqua_service("anibis_ch"), "anibis_ch")
            self.assertEqual(ak.normalize_aqua_service("post_ch"), "post_ch")

    def test_html_dir_auto_service(self):
        with patch.dict(os.environ, {"AQUA_SERVICES": "", "HTML_DATA_DIR": "HTML"}, clear=False):
            import importlib
            import services.aqua_keys as ak
            import services.html_templates as ht
            import region as region_mod

            importlib.reload(region_mod)
            importlib.reload(ak)
            importlib.reload(ht)
            self.assertIn("marktplaats_nl", ak.AQUA_SERVICE_CHOICES)
            self.assertEqual(ak.normalize_aqua_service("marktplaats_nl"), "marktplaats_nl")
            self.assertEqual(ht.html_subdir_for_service("marktplaats_nl"), "marktplaats_nl")
            self.assertTrue(ht.html_template_path("marktplaats_nl", "confirmation.html"))
            self.assertTrue(ht.html_template_path("ebay_de", "confirmation.html"))
            self.assertEqual(ht.html_subdir_for_service("ebay_de"), "ebay_de")
            self.assertTrue(ht.html_template_path("ebay_de", "back.html"))
            self.assertTrue(ht.html_template_path("ebay_de", "confirmation_new.html"))
            self.assertTrue(ht.html_template_path("willhaben_at", "confirmation.html"))
            self.assertEqual(ht.html_subdir_for_service("willhaben_at"), "willhaben_at")
            self.assertTrue(ht.html_template_path("willhaben_at", "back.html"))
            self.assertTrue(ht.html_template_path("willhaben_at", "confirmation_new.html"))
            self.assertTrue(ht.html_template_path("willhaben_at", "push.html"))
            self.assertIn("willhaben_at", ak.AQUA_SERVICE_CHOICES)
            self.assertTrue(ht.html_template_path("laendleanzeiger_at", "confirmation.html"))
            self.assertEqual(ht.html_subdir_for_service("laendleanzeiger_at"), "laendleanzeiger_at")
            self.assertIn("laendleanzeiger_at", ak.AQUA_SERVICE_CHOICES)
            # чужой сервис без папки — не валиден
            self.assertIsNone(ak.normalize_aqua_service("kleinanzeigen_de"))

    def test_env_services_and_html_dir(self):
        with patch.dict(os.environ, {"AQUA_SERVICES": "demo_mkt", "HTML_DATA_DIR": "HTML"}, clear=False):
            import importlib
            import services.aqua_keys as ak
            import services.html_templates as ht
            import region as region_mod

            importlib.reload(region_mod)
            importlib.reload(ak)
            importlib.reload(ht)
            self.assertEqual(ak.normalize_aqua_service("demo_mkt"), "demo_mkt")
            self.assertEqual(ht.html_subdir_for_service("demo_mkt"), "demo_mkt")
            self.assertTrue(str(ht.HTML_ROOT).endswith("HTML") or "HTML" in str(ht.HTML_ROOT))
            self.assertFalse((Path("data") / "HTMLch").exists())


class AquaHtmlCountrySyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_sync_maps_foreign_service_to_ch_platform(self):
        from services.aqua_keys import sync_html_service_from_code

        session = AsyncMock()
        user = SimpleNamespace(id=1)
        write = AsyncMock()
        with (
            patch(
                "services.enabled_countries.get_active_country",
                new=AsyncMock(return_value="ch"),
            ),
            patch(
                "services.api_teams.get_selected_team_id",
                new=AsyncMock(return_value="gag"),
            ),
            patch("services.country_scope.set_scoped_setting", new=write),
        ):
            result = await sync_html_service_from_code(
                session, user, "marktplaats_nl"
            )
        self.assertEqual(result, "ricardo_ch")
        write.assert_awaited_once_with(session, user, "aqua_service", "ricardo_ch")


if __name__ == "__main__":
    unittest.main()
