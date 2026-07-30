"""Привязка входящих по validated email."""
from __future__ import annotations

import unittest

from services.offer_storage import _seller_email_matches


class SellerEmailMatchTests(unittest.TestCase):
    def test_gmail_plus_tag(self):
        self.assertTrue(
            _seller_email_matches("seller+shop@gmail.com", "seller@gmail.com")
        )

    def test_gmail_dots(self):
        self.assertTrue(
            _seller_email_matches("s.e.l.l.e.r@gmail.com", "seller@gmail.com")
        )

    def test_different_emails(self):
        self.assertFalse(
            _seller_email_matches("a@gmx.ch", "b@gmx.ch")
        )


if __name__ == "__main__":
    unittest.main()
