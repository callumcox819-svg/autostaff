# -*- coding: utf-8 -*-
import unittest

from services.country_scope import CROATIA_VALIDATION_DOMAINS, default_validation_domains_for
from services.seller_name import seller_name_eligible_for_validation
from services.validemail_validator import _make_local_part_variants


class CroatiaNameValidationTests(unittest.TestCase):
    def test_validation_domains(self):
        domains = default_validation_domains_for("hr")
        self.assertEqual(domains, CROATIA_VALIDATION_DOMAINS)
        self.assertEqual(domains[0], "net.hr")
        self.assertIn("gmail.com", domains)

    def test_full_name_gets_dot(self):
        self.assertTrue(seller_name_eligible_for_validation("Marko Horvat", country="hr"))
        vs = _make_local_part_variants(
            "Marko Horvat", require_first_and_last=False, country="hr"
        )
        self.assertIn("marko.horvat", vs)
        self.assertIn("markohorvat", vs)

        self.assertTrue(seller_name_eligible_for_validation("Ivan Horvat", country="hr"))
        vs_ivan = _make_local_part_variants(
            "Ivan Horvat", require_first_and_last=False, country="hr"
        )
        self.assertIn("ivan.horvat", vs_ivan)

        self.assertTrue(seller_name_eligible_for_validation("Maria Johansen", country="hr"))
        vs_maria = _make_local_part_variants(
            "Maria Johansen", require_first_and_last=False, country="hr"
        )
        self.assertIn("maria.johansen", vs_maria)

    def test_concatenated_nick_full_local(self):
        self.assertTrue(
            seller_name_eligible_for_validation("BugsBunnyLostinTime", country="hr")
        )
        vs = _make_local_part_variants(
            "BugsBunnyLostinTime", require_first_and_last=False, country="hr"
        )
        self.assertIn("bugsbunnylostintime", vs)

    def test_short_single_name_rejected(self):
        self.assertFalse(seller_name_eligible_for_validation("Mari", country="hr"))
        self.assertFalse(seller_name_eligible_for_validation("Ana", country="hr"))
        self.assertEqual(
            _make_local_part_variants("Mari", require_first_and_last=False, country="hr"),
            [],
        )

    def test_nick_with_digits_and_underscore(self):
        self.assertTrue(seller_name_eligible_for_validation("Anaama_08", country="hr"))
        vs = _make_local_part_variants(
            "Anaama_08", require_first_and_last=False, country="hr"
        )
        self.assertIn("anaama_08", vs)

        self.assertTrue(seller_name_eligible_for_validation("Ana_08", country="hr"))
        vs2 = _make_local_part_variants(
            "Ana_08", require_first_and_last=False, country="hr"
        )
        self.assertIn("ana_08", vs2)

        self.assertFalse(seller_name_eligible_for_validation("Ana_0", country="hr"))

    def test_placeholder_skipped(self):
        self.assertFalse(seller_name_eligible_for_validation("Privatna osoba", country="hr"))

    def test_diacritics_first_last(self):
        self.assertTrue(seller_name_eligible_for_validation("Marko Kovačić", country="hr"))
        vs = _make_local_part_variants(
            "Marko Kovačić", require_first_and_last=False, country="hr"
        )
        self.assertIn("marko.kovacic", vs)


if __name__ == "__main__":
    unittest.main()
