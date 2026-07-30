"""Re: тема не должна показывать чужой лот того же продавца (poputka88-style)."""
from __future__ import annotations

import unittest
from types import SimpleNamespace

from services.offer_matching import (
    _pick_offer_by_subject_in_list,
    gag_link_title_from_mail,
    incoming_subject_binds_offer,
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

    def test_display_title_mailing_bound_uses_offer_when_subject_agrees(self):
        shorts = SimpleNamespace(title="Shorts - Damen - Spitze Weiss - Grösse S neu !", raw_json=None)
        subj = "Re: Shorts - Damen - Spitze Weiss"
        self.assertEqual(
            offer_display_title(subj, shorts, mailing_bound=True),
            "Shorts - Damen - Spitze Weiss - Grösse S neu !",
        )

    def test_display_title_mailing_bound_shows_subject_when_offer_mismatch(self):
        shorts = SimpleNamespace(title="Shorts - Damen - Spitze Weiss - Grösse S neu !", raw_json=None)
        subj = "Re: Haben Sie X-Pole X-Stage Lite Tanzbühne Weiß 45mm 3,00m noch?"
        self.assertEqual(
            offer_display_title(subj, shorts, mailing_bound=True),
            "X-Pole X-Stage Lite Tanzbühne Weiß 45mm 3,00m",
        )

    def test_display_title_prefers_subject_when_offer_mismatch(self):
        shirt = SimpleNamespace(title="Uitshirt voetbal België 2026", raw_json=None)
        subj = "Re: Carte panini 2026"
        self.assertEqual(offer_display_title(subj, shirt), "Carte panini 2026")

    def test_display_title_short_re_subject_not_full_db_title(self):
        tramp = SimpleNamespace(title="Trampoline van Berg", raw_json=None)
        subj = "Re: Trampoline"
        self.assertEqual(offer_display_title(subj, tramp), "Trampoline")

    def test_product_title_aw_ist_lampe(self):
        self.assertEqual(
            product_title_from_subject("Aw: Ist Lampe noch zu haben?"),
            "Lampe",
        )

    def test_title_matches_short_needle_in_long_title(self):
        from services.offer_matching import _offer_title_matches_needle

        self.assertTrue(_offer_title_matches_needle("lampe", "Stehlampe schwarz"))
        self.assertTrue(_offer_title_matches_needle("Lampe", "Lampe"))

    def test_product_title_anfrage_prefix(self):
        self.assertEqual(
            product_title_from_subject("Aw: Anfrage: ProLight Design Hängeleuchte"),
            "ProLight Design Hängeleuchte",
        )

    def test_product_title_ist_noch_zu_haben(self):
        self.assertEqual(
            product_title_from_subject("Re: Ist Nordica Dobermann SLR 165 noch zu haben?"),
            "Nordica Dobermann SLR 165",
        )

    def test_product_title_strips_pretenda_per(self):
        self.assertEqual(
            product_title_from_subject("Re: Pretenda per Minivan VW California"),
            "Minivan VW California",
        )

    def test_subject_agrees_kurze_frage_strips_prefix(self):
        roomba = SimpleNamespace(
            title="Zubehör zu iRobot Roomba Saugroboter",
            raw_json=None,
        )
        subj = "Re: Kurze Frage zu Zubehör zu iRobot Roomba Saugroboter"
        self.assertTrue(subject_title_agrees(subj, roomba))

    def test_product_title_strips_kaufinteresse(self):
        self.assertEqual(
            product_title_from_subject("Re: Kaufinteresse: Saxonet Speedbike"),
            "Saxonet Speedbike",
        )

    def test_product_title_strips_interesse_an(self):
        self.assertEqual(
            product_title_from_subject("Re: Interesse an Thömus Lightrider"),
            "Thömus Lightrider",
        )

    def test_gag_link_title_from_mail_subject_only(self):
        tramp = SimpleNamespace(title="Trampoline van Berg", raw_json=None)
        subj = "Re: Trampoline"
        self.assertEqual(gag_link_title_from_mail(subj, tramp), "Trampoline")

    def test_gag_link_title_rotating_subject_uses_offer_title(self):
        iphone = SimpleNamespace(
            title="iPhone 14 Pro, 128 GB, Schwarz",
            raw_json=None,
        )
        subj = "Kurze Frage zu iPhone 14 Pro, 128 GB, Schwarz"
        self.assertEqual(
            gag_link_title_from_mail(subj, iphone),
            "iPhone 14 Pro, 128 GB, Schwarz",
        )

    def test_pick_mailing_subject_contains_product(self):
        from services.subject_offer import pick_mailing_subject

        subj = pick_mailing_subject("Velo Zürich")
        self.assertIn("Velo Zürich", subj)
        self.assertGreater(len(subj), 8)

    def test_pick_trampoline_offer_among_seller_listings(self):
        tramp = SimpleNamespace(
            title="Trampoline van Berg",
            link="https://www.ricardo.ch/de/a/trampoline",
            raw_json=None,
        )
        sofa = SimpleNamespace(
            title="Grote bank",
            link="https://www.ricardo.ch/de/a/bank",
            raw_json=None,
        )
        hit = _pick_offer_by_subject_in_list([sofa, tramp], "Re: Trampoline")
        self.assertIs(hit, tramp)

    def test_incoming_subject_binds_rejects_unrelated_lot(self):
        book = SimpleNamespace(
            title="Neu erschienen: Tödlicher Rheinfall | Gabriela Kasperski",
            raw_json=None,
        )
        desk = SimpleNamespace(
            title="Zeichentisch höhenverstellbar weiss Metall Gestell verstellbar",
            raw_json=None,
        )
        subj = "AW: Kaufinteresse: Zeichentisch höhenverstellbar weiss Metall Gestell verstellb"
        self.assertFalse(incoming_subject_binds_offer(subj, book))
        self.assertTrue(incoming_subject_binds_offer(subj, desk))

    def test_subject_does_not_match_sofa_when_re_is_armchair(self):
        sofa = SimpleNamespace(title="Beiges Leder-Sofa sehr guter Zustand", raw_json=None)
        chair = SimpleNamespace(
            title="Armlehnstuhl Taormina wood dunkel guter Zustand",
            raw_json=None,
        )
        subj = "Re: Armlehnstuhl Taormina wood dunkel guter Zustand - noch im Verkauf?"
        self.assertFalse(subject_title_agrees(subj, sofa))
        self.assertFalse(incoming_subject_binds_offer(subj, sofa))
        self.assertTrue(subject_title_agrees(subj, chair))
        self.assertTrue(incoming_subject_binds_offer(subj, chair))

    def test_gag_link_title_uses_subject_when_offer_mismatch(self):
        book = SimpleNamespace(title="Tödlicher Rheinfall", raw_json=None)
        subj = "AW: Kaufinteresse: Zeichentisch höhenverstellbar"
        self.assertIn("Zeichentisch", gag_link_title_from_mail(subj, book))


if __name__ == "__main__":
    unittest.main()
