"""Товар/цена/фото на карточке, когда лот привязан."""
from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock

from services.incoming_mail_worker import _incoming_body_dedupe_key, render_mail_text_chunks


class IncomingBodyDedupeTests(unittest.TestCase):
    def test_same_body_different_whitespace_matches(self):
        a = "Bitte ab sofort nur noch die neue Email Adresse n_romano@bluewin.ch verwenden.\n\nVielen Dank"
        b = "Bitte ab sofort nur noch die neue Email Adresse n_romano@bluewin.ch verwenden.  Vielen Dank"
        self.assertEqual(_incoming_body_dedupe_key(a), _incoming_body_dedupe_key(b))

    def test_different_body_no_key_collision(self):
        k1 = _incoming_body_dedupe_key("Erster langer Text vom Verkäufer mit genug Zeichen.")
        k2 = _incoming_body_dedupe_key("Zweiter langer Text vom Verkäufer mit genug Zeichen.")
        self.assertTrue(k1 and k2)
        self.assertNotEqual(k1, k2)


class FirstIncomingCardDisplayTests(unittest.TestCase):
    def test_follow_up_card_shows_title_and_price_when_bound(self):
        chunks = render_mail_text_chunks(
            account_email="inbox@test.com",
            from_name="Domsta",
            from_email="domsta@gmail.com",
            subject="Re: Interesse an Schulranzen",
            body="Hallo",
            offer_id=77302,
            service_label="ricardo.ch",
            product_title="Schulranzen McNeill",
            offer_price="80 .-",
        )
        text = chunks[0]
        self.assertIn("Товар:", text)
        self.assertIn("Цена:", text)
        self.assertIn("Лот:", text)

    def test_first_card_shows_title_and_price(self):
        chunks = render_mail_text_chunks(
            account_email="inbox@test.com",
            from_name="Domsta",
            from_email="domsta@gmail.com",
            subject="Re: Interesse",
            body="Hallo",
            product_title="Schulranzen McNeill",
            offer_price="80 .-",
        )
        text = chunks[0]
        self.assertIn("Товар:", text)
        self.assertIn("Schulranzen McNeill", text)
        self.assertIn("Цена:", text)


class IsFirstInboundMailTests(unittest.IsolatedAsyncioTestCase):
    async def test_no_prior_mails_is_first(self):
        from services.incoming_mail_worker import is_first_inbound_mail_for_seller_offer

        session = AsyncMock()
        session.execute = AsyncMock(return_value=MagicMock(scalar=lambda: 0))
        ok = await is_first_inbound_mail_for_seller_offer(
            session,
            user_id=1,
            account_id=2,
            from_email="a@b.ch",
            resolved_offer_id=77302,
            mail_id=100,
        )
        self.assertTrue(ok)

    async def test_prior_mail_not_first(self):
        from services.incoming_mail_worker import is_first_inbound_mail_for_seller_offer

        session = AsyncMock()
        session.execute = AsyncMock(return_value=MagicMock(scalar=lambda: 2))
        ok = await is_first_inbound_mail_for_seller_offer(
            session,
            user_id=1,
            account_id=2,
            from_email="a@b.ch",
            resolved_offer_id=77302,
            mail_id=100,
        )
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
