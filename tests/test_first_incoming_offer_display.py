"""Товар/цена/фото только на первом входящем от продавца по лоту."""
from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock

from services.incoming_mail_worker import render_mail_text_chunks


class FirstIncomingCardDisplayTests(unittest.TestCase):
    def test_follow_up_card_omits_title_and_price(self):
        chunks = render_mail_text_chunks(
            account_email="inbox@test.com",
            from_name="Domsta",
            from_email="domsta@gmail.com",
            subject="Re: Interesse an Schulranzen",
            body="Hallo",
            service_label="ricardo.ch",
            product_title=None,
            offer_price=None,
        )
        text = chunks[0]
        self.assertNotIn("Товар:", text)
        self.assertNotIn("Цена:", text)
        self.assertIn("Тема:", text)

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
