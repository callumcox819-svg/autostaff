# -*- coding: utf-8 -*-
import unittest

from services.csm_catalog import (
    is_verify_service,
    make_service_key,
    parse_service_key,
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


if __name__ == "__main__":
    unittest.main()
