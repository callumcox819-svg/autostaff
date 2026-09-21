from __future__ import annotations

import unittest

from services.gag_catalog import (
    gag_generate_service,
    gag_service_label,
    normalize_gag_service_code,
)


class GagCatalogTests(unittest.TestCase):
    def test_markt_ch_generates_as_posta_ch(self):
        self.assertEqual(normalize_gag_service_code("markt_ch"), "markt_ch")
        self.assertEqual(gag_generate_service("markt_ch"), "posta_ch")
        self.assertEqual(gag_generate_service("markt.ch"), "posta_ch")
        self.assertEqual(gag_service_label("markt_ch"), "Markt.ch")

    def test_ricardo_stays_ricardo(self):
        self.assertEqual(gag_generate_service("ricardo_ch"), "ricardo_ch")
        self.assertEqual(gag_service_label(""), "Ricardo")
