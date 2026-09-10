import unittest
from unittest.mock import AsyncMock, MagicMock

from services.incoming_mail_worker import (
    is_first_inbound_mail_for_seller,
    render_mail_text_chunks,
    seller_thread_tg_anchor_message_id,
)


class FollowupIncomingCardTests(unittest.IsolatedAsyncioTestCase):
    def test_followup_omits_lot_product_price(self):
        first = render_mail_text_chunks(
            account_email="buyer@gmail.com",
            inbox_label="Maria",
            from_name="baris",
            from_email="baris@hotmail.com",
            subject="Philips 3200",
            body="Hoe gaan we dat regelen?",
            offer_id=114582,
            service_label="marktplaats.nl",
            product_title="Philips 3200 serie",
            offer_price="225 €",
        )[0]
        self.assertIn("Лот:", first)
        self.assertIn("Товар:", first)
        self.assertIn("225", first)

        follow = render_mail_text_chunks(
            account_email="buyer@gmail.com",
            inbox_label="Maria",
            from_name="baris",
            from_email="baris@hotmail.com",
            subject="Philips 3200",
            body="Hoe gaan we dat regelen?",
            offer_id=None,
            service_label=None,
            product_title=None,
            offer_price=None,
        )[0]
        self.assertNotIn("Лот:", follow)
        self.assertNotIn("Товар:", follow)
        self.assertNotIn("Цена:", follow)
        self.assertNotIn("Сервис:", follow)
        self.assertIn("Тема:", follow)
        self.assertIn("Philips 3200", follow)

    async def test_first_seller_false_when_prior_tg_card(self):
        session = AsyncMock()
        result = MagicMock()
        result.scalar.return_value = 1
        session.execute = AsyncMock(return_value=result)
        ok = await is_first_inbound_mail_for_seller(
            session,
            user_id=1,
            account_id=2,
            from_email="baris_aksu45@hotmail.com",
            mail_id=99,
        )
        self.assertFalse(ok)

    async def test_first_seller_true_without_prior(self):
        session = AsyncMock()
        result = MagicMock()
        result.scalar.return_value = 0
        session.execute = AsyncMock(return_value=result)
        ok = await is_first_inbound_mail_for_seller(
            session,
            user_id=1,
            account_id=2,
            from_email="baris_aksu45@hotmail.com",
            mail_id=99,
        )
        self.assertTrue(ok)

    async def test_anchor_prefers_convlink(self):
        session = AsyncMock()
        conv = MagicMock(tg_message_id=555)
        tid = await seller_thread_tg_anchor_message_id(
            session,
            user_id=1,
            account_id=2,
            from_email="a@b.com",
            conv=conv,
        )
        self.assertEqual(tid, 555)
        session.execute.assert_not_called()


if __name__ == "__main__":
    unittest.main()
