# -*- coding: utf-8 -*-
import unittest

from services.autoparse import (
    build_start_filters,
    default_platform_for_country,
    listing_to_item,
    merge_filters_keep_user,
    parser_iso_country,
    pick_existing_task,
    pick_task_for_filters,
    resolve_local_start_filters,
    summarize_filters,
)


class AutoparseMapTests(unittest.TestCase):
    def test_country_platforms(self):
        self.assertEqual(default_platform_for_country("nl"), "marktplaats")
        self.assertEqual(default_platform_for_country("de"), "kleinanzeigen")
        self.assertEqual(default_platform_for_country("hr"), "vinted")
        self.assertEqual(default_platform_for_country("hu"), "vinted")
        self.assertEqual(parser_iso_country("uk"), "gb")
        from services.autoparse import AUTOPARSE_PLATFORM_KEY

        self.assertEqual(AUTOPARSE_PLATFORM_KEY, "autoparse_platform")

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
        self.assertEqual(f["created_at_period"], "7d")
        self.assertNotIn("countries", f)
        self.assertNotIn("seller_email", f)

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

    def test_pick_filters_same_platform_only(self):
        tasks = [
            {"task_id": 9, "platform": "vinted", "status": "running", "filters": {"seller_email": True}},
            {
                "task_id": 368741,
                "platform": "marktplaats",
                "status": "stopped",
                "filters": {"price_min": 5, "stop_words": ["x"]},
            },
        ]
        hit = pick_task_for_filters(tasks, platform="marktplaats")
        self.assertEqual(hit["task_id"], 368741)

    def test_resolve_prefers_xp_then_saved(self):
        plat = {
            "platform": "marktplaats",
            "countries": ["nl"],
            "supported_filters": [
                "internal_listing_count",
                "price_min",
                "seller_email",
                "countries",
            ],
        }
        xp = {
            "task_id": 368741,
            "filters": {"price_min": 10, "seller_email": True, "internal_listing_count": 500},
        }
        f, src = resolve_local_start_filters(
            plat=plat,
            bot_cc="nl",
            json_count=80,
            infinite=True,
            saved={"price_min": 1},
            xp_task=xp,
        )
        self.assertIn("задач", src)
        self.assertEqual(f["price_min"], 10)
        self.assertEqual(f["internal_listing_count"], 80)
        self.assertTrue(f["seller_email"])

        f2, src2 = resolve_local_start_filters(
            plat=plat,
            bot_cc="nl",
            json_count=40,
            infinite=False,
            saved={"price_min": 3},
            xp_task=None,
        )
        self.assertEqual(src2, "сохранённые фильтры")
        self.assertEqual(f2["price_min"], 3)
        self.assertEqual(f2["countries"], ["nl"])

    def test_everywhere_is_a_category_label(self):
        from services.autoparse import category_label, toggle_category_list

        self.assertEqual(category_label("everywhere"), "Смотреть везде")
        self.assertEqual(category_label("see_everywhere"), "Смотреть везде")
        cur = toggle_category_list([], "cars", all_values=["everywhere", "cars"])
        self.assertEqual(cur, ["cars"])
        cur = toggle_category_list(cur, "everywhere", all_values=["everywhere", "cars"])
        self.assertEqual(cur, ["everywhere", "cars"])


if __name__ == "__main__":
    unittest.main()
