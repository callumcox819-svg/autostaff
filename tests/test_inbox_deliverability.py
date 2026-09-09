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

    def test_build_inbox_copy_no_links_no_re(self):
        subj, body = build_inbox_mailing_copy("Gastro servies")
        self.assertFalse(subj.lower().startswith("re:"))
        self.assertNotIn("http://", body.lower())
        self.assertNotIn("https://", body.lower())
        self.assertTrue(len(body) < 200)

    def test_defaults_inbox_not_fast(self):
        with patch.dict(os.environ, {}, clear=False):
            for k in (
                "MAILING_FAST_MODE",
                "MAILING_INBOX_SUCCESS_PROFILE",
                "MAILING_BODY_VARIATION",
                "INBOX_STAGGER_MS",
                "MAILING_MAX_PER_ACCOUNT_HOUR",
            ):
                os.environ.pop(k, None)
            self.assertFalse(mailing_fast_mode())
            self.assertTrue(mailing_inbox_success_profile())
            self.assertTrue(mailing_body_variation())
            self.assertEqual(inbox_stagger_ms(), 80)
            self.assertEqual(mailing_max_per_account_hour(), 40)

    def test_fast_mode_zero_stagger_default(self):
        with patch.dict(os.environ, {"MAILING_FAST_MODE": "1"}, clear=False):
            os.environ.pop("INBOX_STAGGER_MS", None)
            self.assertTrue(mailing_fast_mode())
            self.assertEqual(inbox_stagger_ms(), 0)

    def test_finalize_keeps_title_in_subject_path(self):
        subj, body = finalize_inbox_mail(
            "Vraag over OFFER",
            "Beste, is OFFER nog beschikbaar?",
            offer_title="Fiets",
        )
        self.assertIn("Fiets", body)
        self.assertNotIn("OFFER", body)


if __name__ == "__main__":
    unittest.main()
