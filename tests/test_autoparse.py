# -*- coding: utf-8 -*-
import unittest

from services.autoparse import (
    build_start_filters,
    default_platform_for_country,
    listing_to_item,
    merge_filters_keep_user,
    parser_iso_country,
    pick_existing_task,
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

    def test_merge_keeps_xproject_filters_only_count(self):
        existing = {
            "categories": [1, 2],
            "price_min": 10,
            "seller_email": False,
            "delivery": False,
            "internal_listing_count": 500,
            "stop_words": ["spam"],
        }
        f = merge_filters_keep_user(existing, json_count=80)
        self.assertEqual(f["categories"], [1, 2])
        self.assertEqual(f["price_min"], 10)
        self.assertEqual(f["stop_words"], ["spam"])
        self.assertEqual(f["internal_listing_count"], 80)
        self.assertNotIn("seller_email", f)
        self.assertNotIn("delivery", f)

    def test_pick_running_same_platform(self):
        tasks = [
            {"task_id": 1, "platform": "vinted", "status": "stopped"},
            {"task_id": 368741, "platform": "vinted", "status": "running"},
        ]
        hit = pick_existing_task(tasks, platform="vinted")
        self.assertEqual(hit["task_id"], 368741)


if __name__ == "__main__":
    unittest.main()
