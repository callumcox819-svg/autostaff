# -*- coding: utf-8 -*-
import os
import unittest
from unittest.mock import patch

from services.mailing_deliverability import (
    build_inbox_mailing_copy,
    finalize_inbox_mail,
    inbox_stagger_ms,
    mailing_body_variation,
    mailing_fast_mode,
    mailing_inbox_success_profile,
    mailing_max_per_account_hour,
    sanitize_subject_for_inbox,
)


class InboxDeliverabilityTests(unittest.TestCase):
    def test_strips_fake_re_prefix(self):
        self.assertEqual(sanitize_subject_for_inbox("Re: OFFER"), "OFFER")
        self.assertEqual(sanitize_subject_for_inbox("Aw: Vraag over Bike"), "Vraag over Bike")

    def test_decodes_html_entities_in_subject(self):
        self.assertEqual(
            sanitize_subject_for_inbox("Rahmen Gr 40&#x2F;50"),
            "Rahmen Gr 40/50",
        )

    def test_build_inbox_copy_no_links_no_re(self):
        subj, body = build_inbox_mailing_copy("Gastro servies")
        self.assertFalse(subj.lower().startswith("re:"))
        self.assertNotIn("http://", body.lower())
        self.assertNotIn("https://", body.lower())
        self.assertTrue(len(body) < 200)

    def test_defaults_fast_no_hourly_cap(self):
        with patch.dict(os.environ, {}, clear=False):
            for k in (
                "MAILING_FAST_MODE",
                "MAILING_INBOX_SUCCESS_PROFILE",
                "MAILING_BODY_VARIATION",
                "INBOX_STAGGER_MS",
                "MAILING_MAX_PER_ACCOUNT_HOUR",
            ):
                os.environ.pop(k, None)
            self.assertTrue(mailing_fast_mode())
            self.assertTrue(mailing_inbox_success_profile())
            self.assertTrue(mailing_body_variation())
            self.assertEqual(inbox_stagger_ms(), 0)
            self.assertEqual(mailing_max_per_account_hour(), 0)

    def test_slow_mode_stagger(self):
        with patch.dict(os.environ, {"MAILING_FAST_MODE": "0"}, clear=False):
            os.environ.pop("INBOX_STAGGER_MS", None)
            self.assertFalse(mailing_fast_mode())
            self.assertEqual(inbox_stagger_ms(), 80)

    def test_no_double_greeting(self):
        from services.mailing_deliverability import add_inbox_body_variation

        with patch.dict(os.environ, {"MAILING_BODY_VARIATION": "1"}, clear=False):
            out = add_inbox_body_variation(
                "Goedendag, kan ik nog reageren op de bank?\n\nDank je!"
            )
        self.assertEqual(out.lower().count("goedendag"), 1)
        self.assertNotIn("goedemiddag", out.lower().split("goedendag")[0])
        # Не должно быть двух приветствий подряд в начале
        first_block = out.split("\n\n", 1)[0].lower()
        self.assertTrue(first_block.startswith("goedendag"))

    def test_ch_fallback_is_german_and_uses_sender_name(self):
        with patch.dict(os.environ, {"MAILING_BODY_VARIATION": "1"}, clear=False):
            subject, body = build_inbox_mailing_copy(
                "Thule Dachträger",
                country="ch",
                sender_name="Anna",
            )
        self.assertNotIn("vraag", subject.lower())
        self.assertNotIn("beschikbaar", body.lower())
        self.assertTrue(
            any(word in body.lower() for word in ("verfügbar", "artikel", "angebot", "verkauft"))
        )
        self.assertIn("Anna", body)

    def test_user_preset_is_not_replaced_or_given_foreign_signature(self):
        subject, body = finalize_inbox_mail(
            "Frage zu OFFER",
            "Guten Tag, ist OFFER noch verfügbar?\n\nFreundliche Grüße\nAnna",
            offer_title="Fahrrad",
            country="ch",
            sender_name="Anna",
            vary_body=False,
        )
        self.assertEqual(subject, "Frage zu OFFER")
        self.assertIn("Fahrrad noch verfügbar", body)
        self.assertNotIn("Met vriendelijke groet", body)
        self.assertEqual(body.count("Anna"), 1)

    def test_sender_signature_is_added_when_preset_omits_placeholder(self):
        _, body = finalize_inbox_mail(
            "OFFER",
            "Guten Tag, ist der Artikel noch verfügbar?",
            country="ch",
            sender_name="Anna Gremlis",
            vary_body=False,
        )
        self.assertTrue(body.endswith("Freundliche Grüße\nAnna Gremlis"))


if __name__ == "__main__":
    unittest.main()
