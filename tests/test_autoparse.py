# -*- coding: utf-8 -*-
import unittest

from services.autoparse import (
    build_start_filters,
    default_platform_for_country,
    listing_to_item,
    parser_iso_country,
)


class AutoparseMapTests(unittest.TestCase):
    def test_country_platforms(self):
        self.assertEqual(default_platform_for_country("nl"), "marktplaats")
        self.assertEqual(default_platform_for_country("de"), "kleinanzeigen")
        self.assertEqual(default_platform_for_country("hr"), "vinted")
        self.assertEqual(default_platform_for_country("hu"), "vinted")
        self.assertEqual(parser_iso_country("uk"), "gb")

    def test_listing_to_bot_json(self):
        item = listing_to_item(
            {
                "title": "Nike Air",
                "price": 74.9,
                "currency": "EUR",
                "url": "https://www.vinted.de/items/1",
                "image": "https://img.example/a.jpg",
                "seller_name": "Maria Johansen",
                "platform": "vinted",
                "country": "de",
                "row_id": 12,
            }
        )
        self.assertEqual(item["item_title"], "Nike Air")
        self.assertEqual(item["item_person_name"], "Maria Johansen")
        self.assertIn("74.9", item["item_price"])
        self.assertTrue(item["item_link"].startswith("https://"))

    def test_filters_skip_unknown_country_key(self):
        plat = {
            "platform": "kleinanzeigen",
            "countries": ["de"],
            "supported_filters": ["internal_listing_count", "seller_email", "created_at_period"],
        }
        f = build_start_filters(plat, bot_cc="de", json_count=50, infinite=False)
        self.assertEqual(f["internal_listing_count"], 50)
        self.assertTrue(f["seller_email"])
        self.assertEqual(f["created_at_period"], "7d")
        self.assertNotIn("countries", f)

        vinted = {
            "platform": "vinted",
            "countries": ["hr", "de"],
            "supported_filters": ["countries", "internal_listing_count", "created_at_period"],
        }
        f2 = build_start_filters(vinted, bot_cc="hr", json_count=20, infinite=True)
        self.assertEqual(f2["countries"], ["hr"])
        self.assertEqual(f2["created_at_period"], "fresh")


if __name__ == "__main__":
    unittest.main()
