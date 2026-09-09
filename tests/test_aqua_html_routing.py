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
            self.assertEqual(ak.AQUA_SERVICE_CHOICES, ())
            self.assertIsNone(ak.normalize_aqua_service("ricardo_ch"))
            self.assertIsNone(ak.normalize_aqua_service("tutti_ch"))

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
