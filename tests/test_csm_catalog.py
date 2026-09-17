# -*- coding: utf-8 -*-
import unittest

from services.csm_catalog import (
    is_verify_service,
    make_service_key,
    parse_service_key,
    platforms_for_country,
    service_key_label,
)


class CsmCatalogTests(unittest.TestCase):
    def test_parse_and_make(self):
        self.assertEqual(parse_service_key("depop_us"), ("depop", "us"))
        self.assertEqual(parse_service_key("depop_verify_all"), ("depop", "verify_all"))
        self.assertEqual(make_service_key("vinted", "fr"), "vinted_fr")
        self.assertEqual(make_service_key("depop", "verify"), "depop_verify_all")
        self.assertTrue(is_verify_service("depop_verify_all"))
        self.assertFalse(is_verify_service("depop_us"))
        self.assertIn("Depop", service_key_label("depop_us"))

    def test_country_first_services(self):
        nl = [p for p, _, _ in platforms_for_country("nl")]
        self.assertIn("marktplaats", nl)
        self.assertIn("2dehands", nl)
        de = [p for p, _, _ in platforms_for_country("de")]
        self.assertIn("kleinanzeigen", de)
        at = [p for p, _, _ in platforms_for_country("at")]
        self.assertIn("willhaben", at)
        self.assertIn("laendleanzeiger", at)
        self.assertTrue(service_key_label("marktplaats_nl").startswith("Нидерланды"))
        self.assertTrue(service_key_label("laendleanzeiger_at").startswith("Австрия"))
        self.assertEqual(make_service_key("laendleanzeiger", "at"), "laendleanzeiger_at")


if __name__ == "__main__":
    unittest.main()
