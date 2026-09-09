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
        self.assertIn("maria", vs)  # 5 букв — ок
        self.assertGreaterEqual(len(vs), 4)

        a = {"item_person_name": "Maria Johansen", "item_link": "https://a/1"}
        b = {"item_person_name": "Maria  Johansen", "item_link": "https://a/2"}
        self.assertEqual(seller_name_key_from_item(a), seller_name_key_from_item(b))
        self.assertEqual(seller_name_key("Maria Johansen"), seller_name_key("maria johansen"))

    def test_reject_short_nick_brand_city_keep_long_name(self):
        from services.seller_name import (
            is_usable_single_local,
            seller_name_eligible_for_validation,
        )

        self.assertFalse(is_usable_single_local("jan"))
        self.assertFalse(is_usable_single_local("auto"))
        self.assertFalse(is_usable_single_local("audi"))
        self.assertFalse(is_usable_single_local("amersfoort"))
        self.assertTrue(is_usable_single_local("mariasto"))

        self.assertFalse(seller_name_eligible_for_validation("Jan"))
        self.assertFalse(seller_name_eligible_for_validation("Auto"))
        self.assertFalse(seller_name_eligible_for_validation("Amersfoort"))
        self.assertTrue(seller_name_eligible_for_validation("mariasto"))

        self.assertEqual(
            _make_local_part_variants("Jan", require_first_and_last=False),
            [],
        )
        self.assertEqual(
            _make_local_part_variants("Auto", require_first_and_last=False),
            [],
        )
        self.assertEqual(
            _make_local_part_variants("Amersfoort", require_first_and_last=False),
            [],
        )
        self.assertIn(
            "mariasto",
            _make_local_part_variants("mariasto", require_first_and_last=False),
        )
        # короткие имя/фамилия по отдельности не пробиваем, first.last — да
        vs = _make_local_part_variants("Jan de Vries", require_first_and_last=False)
        self.assertIn("jan.vries", vs)
        self.assertNotIn("jan", vs)

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

    def test_chs_only_from_saved_output_with_email(self):
        from services.seller_blacklist import seller_keys_from_saved_output

        keys = seller_keys_from_saved_output(
            [
                {"item_person_name": "Hans Mueller", "validated_emails": ["h@x.ch"]},
                {"item_person_name": "No Mail", "validated_emails": []},
                {"item_person_name": "Skip"},
            ]
        )
        self.assertEqual(keys, {"hans mueller"})

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

    def test_retry_phase_does_not_count_all_as_no_email(self):
        from handlers.validation import _format_validation_status

        text = _format_validation_status(
            finished=False,
            user_line="",
            processed=0,
            total=600,
            added=0,
            duplicates=0,
            in_blacklist=0,
            added_blacklist=166,
            short_nicks=17,
            no_email=423,
            errors=176,
            phase="api_retry",
            api_retry_queued=176,
            api_retry_done=0,
        )
        self.assertIn("Повтор после сбоев API", text)
        self.assertIn("Без email: <b>0</b>", text)
        self.assertNotIn("Ошибок API", text)


if __name__ == "__main__":
    unittest.main()
