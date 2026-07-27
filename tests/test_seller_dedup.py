"""Один продавец в VOID — один проход валидации и одно сохранение."""
from __future__ import annotations

import unittest

from services.seller_blacklist import seller_name_key, seller_name_key_from_item
from services.validemail_validator import _make_local_part_variants


class SellerDedupTests(unittest.TestCase):
    def test_local_variants_maria(self):
        vs = _make_local_part_variants("Maria Johansen", require_first_and_last=False)
        self.assertIn("maria.johansen", vs)
        self.assertIn("mariajohansen", vs)
        self.assertGreaterEqual(len(vs), 4)

        a = {"item_person_name": "Maria Johansen", "item_link": "https://a/1"}
        b = {"item_person_name": "Maria  Johansen", "item_link": "https://a/2"}
        self.assertEqual(seller_name_key_from_item(a), seller_name_key_from_item(b))
        self.assertEqual(seller_name_key("Maria Johansen"), seller_name_key("maria johansen"))


if __name__ == "__main__":
    unittest.main()
