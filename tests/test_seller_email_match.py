"""Привязка входящих по validated email."""
from __future__ import annotations

import unittest

from services.offer_matching import canon_seller_email
from services.offer_storage import _seller_email_matches, normalize_incoming_seller_email
from services.mailing_send_log import seller_emails_equivalent


class SellerEmailMatchTests(unittest.TestCase):
    def test_gmail_plus_tag(self):
        self.assertTrue(
            _seller_email_matches("seller+shop@gmail.com", "seller@gmail.com")
        )

    def test_gmail_dots(self):
        self.assertTrue(
            _seller_email_matches("s.e.l.l.e.r@gmail.com", "seller@gmail.com")
        )

    def test_michaela_lipburger_gmail_dots(self):
        """Ответ без точек ↔ validated с точками → один продавец / один лот."""
        stored = "michaela.lipburger@gmail.com"
        inbound = "michaelalipburger@gmail.com"
        self.assertEqual(
            canon_seller_email(stored),
            canon_seller_email(inbound),
        )
        self.assertEqual(
            normalize_incoming_seller_email(inbound),
            "michaelalipburger@gmail.com",
        )
        self.assertTrue(_seller_email_matches(stored, inbound))
        self.assertTrue(seller_emails_equivalent(stored, inbound))

    def test_different_emails(self):
        self.assertFalse(
            _seller_email_matches("a@gmx.ch", "b@gmx.ch")
        )


if __name__ == "__main__":
    unittest.main()
