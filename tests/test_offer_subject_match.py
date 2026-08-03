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

    def test_product_title_guten_tag_nochn_verfugbar_preset(self):
        title = "CNF Belt Octopus SWISS MADE - Nuova - White"
        subj = f"Re: Guten Tag, {title} noch verfügbar?"
        self.assertEqual(product_title_from_subject(subj), title)

    def test_inbound_subject_matches_rotated_send_subject(self):
        from services.subject_offer import offer_title_from_inbound_subject, pick_mailing_subject

        title = "Stardupp Ultra SUP Paddle"
        sent = pick_mailing_subject(title)
        self.assertEqual(offer_title_from_inbound_subject(f"Re: {sent}"), title)

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

    def test_aw_subject_plain_title_with_noch_im_verkauf_trailer(self):
        from services.subject_offer import offer_title_from_inbound_subject

        subj = (
            "AW: Kärcher Akku-Staubsauger BVL 3/1 Bp inkl. Akku und Ladegerät "
            "- noch im Verk…"
        )
        title = offer_title_from_inbound_subject(subj)
        self.assertIn("Kärcher Akku-Staubsauger", title)
        self.assertNotIn("noch im Verk", title.lower())

    def test_subjects_for_inbound_resolve_quoted_betreff(self):
        from services.subject_offer import subjects_for_inbound_resolve

        body = (
            "Ja !\n\n-----Ursprüngliche Nachricht-----\n"
            "Betreff: Kärcher Akku-Staubsauger BVL 3/1 Bp inkl. Akku und Ladegerät\n"
        )
        subs = subjects_for_inbound_resolve("AW: Kärcher …", body)
        self.assertTrue(any("Kärcher Akku-Staubsauger" in s for s in subs))

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


class InboundQuotedBodyTests(unittest.TestCase):
    def test_quoted_nachfragen_ob_offer_in_body(self):
        from services.subject_offer import subjects_for_inbound_resolve

        body = (
            "Ciao Anna, klar ist ok.\n\n"
            ">> Hallo, ich wollte nachfragen, ob Sammlung Sternenschweif Kinderbücher noch angeboten wird."
        )
        subj = "Re: Sammlung Sternenschweif Kinderbücher - noch da?"
        tries = subjects_for_inbound_resolve(subj, body)
        joined = " | ".join(tries).lower()
        self.assertIn("sternenschweif", joined)

    def test_sidi_body_exact_user_case(self):
        from services.subject_offer import primary_inbound_product_needle, subjects_for_inbound_resolve

        body = (
            "Noch zu haben\n\n"
            "Anna Kerher <blasterh183@gmail.com> schrieb am Sa. 1. Aug. 2026 um 22:19:\n"
            "Hallo, ist Sidi racing Schuhe Rex air noch nicht verkauft?"
        )
        tries = subjects_for_inbound_resolve("Noch zu haben", body)
        self.assertFalse(any(t.lower().strip() == "noch zu haben" for t in tries))
        needle = primary_inbound_product_needle("Noch zu haben", body)
        self.assertIn("sidi", needle.lower())
        self.assertIn("rex air", needle.lower())

    def test_weak_subject_skipped_when_body_has_offer(self):
        from services.subject_offer import subjects_for_inbound_resolve

        body = ">> Hallo, ist Lampe LED noch nicht verkauft?"
        tries = subjects_for_inbound_resolve("Noch zu haben", body)
        self.assertTrue(any("lampe" in t.lower() for t in tries))
        self.assertNotIn("noch zu haben", [t.lower() for t in tries])


if __name__ == "__main__":
    unittest.main()
