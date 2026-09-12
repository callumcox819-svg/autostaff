"""HTML routing: сервисы из AQUA_SERVICES, шаблоны в data/HTML/."""

from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest.mock import patch


class AquaHtmlRoutingTests(unittest.TestCase):
    def test_no_swiss_services_by_default(self):
        with patch.dict(os.environ, {"AQUA_SERVICES": ""}, clear=False):
            import importlib
            import services.aqua_keys as ak

            importlib.reload(ak)
            self.assertIsNone(ak.normalize_aqua_service("ricardo_ch"))
            self.assertIsNone(ak.normalize_aqua_service("tutti_ch"))

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


if __name__ == "__main__":
    unittest.main()
