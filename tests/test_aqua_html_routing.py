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
            self.assertEqual(ak.html_dir_for_service("markt_ch"), "post_ch")
            self.assertEqual(ak.html_dir_for_service("posta_ch"), "post_ch")

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
            self.assertEqual(ak.normalize_aqua_service("kleinanzeigen_de"), "kleinanzeigen_de")
            self.assertTrue(ht.html_template_path("kleinanzeigen_de", "confirmation.html"))
            self.assertIsNone(ak.normalize_aqua_service("no_such_market_xx"))
            self.assertEqual(ak.normalize_aqua_service("olx_pt"), "olx_pt")
            self.assertEqual(ht.html_subdir_for_service("olx_pt"), "olx_pt")
            self.assertTrue(ht.html_template_path("olx_pt", "confirmation.html"))
            self.assertTrue(ht.html_template_path("olx_pt", "back.html"))
            self.assertTrue(ht.html_template_path("olx_pt", "push.html"))
            self.assertTrue(ht.html_template_path("olx_pt", "confirmation_new.html"))
            self.assertIn("olx_pt", ak.AQUA_SERVICE_CHOICES)
            self.assertEqual(ak.normalize_aqua_service("jofogas_hu"), "jofogas_hu")
            self.assertEqual(ht.html_subdir_for_service("jofogas_hu"), "jofogas_hu")
            self.assertTrue(ht.html_template_path("jofogas_hu", "confirmation.html"))
            self.assertTrue(ht.html_template_path("jofogas_hu", "back.html"))
            self.assertTrue(ht.html_template_path("jofogas_hu", "push.html"))
            self.assertTrue(ht.html_template_path("jofogas_hu", "confirmation_new.html"))
            self.assertIn("jofogas_hu", ak.AQUA_SERVICE_CHOICES)

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

    async def test_germany_hustle_resolves_kleinanzeigen_html(self):
        from services.aqua_keys import is_valid_aqua_service, resolve_html_service
        from services.html_templates import html_template_path

        session = AsyncMock()
        user = SimpleNamespace(id=1)
        cfg = SimpleNamespace(team_id="hustle", service_code="kleinanzeigen_de")
        with (
            patch(
                "services.enabled_countries.get_active_country",
                new=AsyncMock(return_value="de"),
            ),
            patch(
                "services.api_teams.get_selected_team_config",
                new=AsyncMock(return_value=cfg),
            ),
        ):
            svc = await resolve_html_service(session, user)
        self.assertEqual(svc, "kleinanzeigen_de")
        self.assertTrue(is_valid_aqua_service(svc))
        self.assertTrue(html_template_path(svc, "confirmation.html"))


if __name__ == "__main__":
    unittest.main()

