"""Re: тема не должна показывать чужой лот того же продавца (poputka88-style)."""
from __future__ import annotations

import unittest
from types import SimpleNamespace

from services.offer_matching import (
    _pick_offer_by_subject_in_list,
    narkologia_link_title_from_mail,
    offer_display_title,
    product_title_from_subject,
    subject_match_score,
    subject_title_agrees,
)


class OfferSubjectMatchTests(unittest.TestCase):
    def test_product_title_from_re_subject(self):
        self.assertEqual(
            product_title_from_subject("Re: Carte panini 2026"),
            "Carte panini 2026",
        )

    def test_subject_agrees_panini_not_uitshirt(self):
        panini = SimpleNamespace(title="Carte panini 2026", raw_json=None)
        shirt = SimpleNamespace(title="Uitshirt voetbal België 2026", raw_json=None)
        subj = "Re: Carte panini 2026"
        self.assertTrue(subject_title_agrees(subj, panini))
        self.assertFalse(subject_title_agrees(subj, shirt))

    def test_year_alone_does_not_inflate_score(self):
        panini = SimpleNamespace(title="Carte panini 2026", raw_json=None)
        shirt = SimpleNamespace(title="Uitshirt voetbal België 2026", raw_json=None)
        subj = "Re: Carte panini 2026"
        self.assertGreater(subject_match_score(subj, panini), subject_match_score(subj, shirt))

    def test_display_title_prefers_subject_when_offer_mismatch(self):
        shirt = SimpleNamespace(title="Uitshirt voetbal België 2026", raw_json=None)
        subj = "Re: Carte panini 2026"
        self.assertEqual(offer_display_title(subj, shirt), "Carte panini 2026")

    def test_display_title_short_re_subject_not_full_db_title(self):
        tramp = SimpleNamespace(title="Trampoline van Berg", raw_json=None)
        subj = "Re: Trampoline"
        self.assertEqual(offer_display_title(subj, tramp), "Trampoline")

    def test_narkologia_link_title_from_mail_subject_only(self):
        tramp = SimpleNamespace(title="Trampoline van Berg", raw_json=None)
        subj = "Re: Trampoline"
        self.assertEqual(narkologia_link_title_from_mail(subj, tramp), "Trampoline")

    def test_pick_trampoline_offer_among_seller_listings(self):
        tramp = SimpleNamespace(
            title="Trampoline van Berg",
            link="https://www.2dehands.be/v/trampoline",
            raw_json=None,
        )
        sofa = SimpleNamespace(
            title="Grote bank",
            link="https://www.2dehands.be/v/bank",
            raw_json=None,
        )
        hit = _pick_offer_by_subject_in_list([sofa, tramp], "Re: Trampoline")
        self.assertIs(hit, tramp)


if __name__ == "__main__":
    unittest.main()
