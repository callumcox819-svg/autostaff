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
        self.assertIn("johansen", vs)
        self.assertIn("maria", vs)
        self.assertGreaterEqual(len(vs), 6)

        a = {"item_person_name": "Maria Johansen", "item_link": "https://a/1"}
        b = {"item_person_name": "Maria  Johansen", "item_link": "https://a/2"}
        self.assertEqual(seller_name_key_from_item(a), seller_name_key_from_item(b))
        self.assertEqual(seller_name_key("Maria Johansen"), seller_name_key("maria johansen"))

    def test_skip_already_in_db_is_not_blacklist(self):
        from services.validemail_validator import classify_json_seller_skip

        self.assertEqual(
            classify_json_seller_skip(
                "hans mueller",
                blacklist=set(),
                already_validated={"hans mueller"},
                batch_seen=set(),
            ),
            "already_in_db",
        )
        self.assertEqual(
            classify_json_seller_skip(
                "hans mueller",
                blacklist={"hans mueller"},
                already_validated=set(),
                batch_seen=set(),
            ),
            "blacklisted",
        )
        self.assertEqual(
            classify_json_seller_skip(
                "hans mueller",
                blacklist=set(),
                already_validated=set(),
                batch_seen={"hans mueller"},
            ),
            "duplicates",
        )

    def test_status_separates_already_in_db_from_chs(self):
        from handlers.validation import _format_validation_status

        text = _format_validation_status(
            finished=True,
            user_line="",
            processed=606,
            total=606,
            added=0,
            duplicates=40,
            in_blacklist=0,
            added_blacklist=2,
            short_nicks=0,
            no_email=359,
            errors=176,
            already_in_db=117,
            listings_in_file=606,
            offers_eligible=447,
        )
        self.assertIn("Уже в БД", text)
        self.assertIn("<b>117</b>", text)
        self.assertIn("ЧС: <b>2</b>", text)
        self.assertIn("Новых email", text)


if __name__ == "__main__":
    unittest.main()
