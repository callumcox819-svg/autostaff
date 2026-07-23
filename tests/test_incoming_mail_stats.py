"""Статистика входящих: mailing_bound считается как живой продавец."""
from __future__ import annotations

import unittest
from types import SimpleNamespace

from services.incoming_mail_stats import classify_incoming_row


class IncomingMailStatsTests(unittest.TestCase):
    def test_seller_matched_via_offer_email_id(self):
        row = SimpleNamespace(
            from_email="seller@icloud.com",
            from_name="",
            subject="Re: Kapstok",
            body="",
            resolved_offer_email_id=42,
            resolved_offer_id=7,
            mailing_bound=False,
        )
        self.assertEqual(classify_incoming_row(row), "seller_matched")

    def test_seller_matched_via_mailing_bound(self):
        row = SimpleNamespace(
            from_email="seller@icloud.com",
            from_name="",
            subject="Re: Kapstok",
            body="",
            resolved_offer_email_id=None,
            resolved_offer_id=7,
            mailing_bound=True,
        )
        self.assertEqual(classify_incoming_row(row), "seller_matched")

    def test_seller_matched_via_re_subject_without_mailing_bound(self):
        row = SimpleNamespace(
            from_email="seller@icloud.com",
            from_name="",
            subject="Re: Kapstok",
            body="",
            resolved_offer_email_id=None,
            resolved_offer_id=7,
            mailing_bound=False,
        )
        self.assertEqual(classify_incoming_row(row), "seller_matched")

    def test_marketing_sender_classified_as_platform(self):
        row = SimpleNamespace(
            from_email="admin@latestcasinobonuses.com",
            from_name="",
            subject="LCB New Brand Alert",
            body="",
            resolved_offer_email_id=None,
            resolved_offer_id=99,
            mailing_bound=False,
        )
        self.assertEqual(classify_incoming_row(row), "platform")


if __name__ == "__main__":
    unittest.main()
