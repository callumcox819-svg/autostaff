import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from handlers.incoming_mail import (
    _aqua_link_user_error,
    _offer_id_from_incoming_card_message,
    _sync_incoming_mail_offer_with_card,
)


class _Msg:
    def __init__(self, *, html_text: str | None = None, text: str | None = None):
        self.html_text = html_text
        self.text = text


class IncomingCardLotParseTests(unittest.TestCase):
    def test_parses_lot_from_html_card(self):
        html = (
            "<b>От:</b> zaur@bluewin.ch\n"
            "<b>Лот:</b> <code>89574</code>\n"
            "<b>Товар:</b> Mobiles Kühlgerät"
        )
        self.assertEqual(_offer_id_from_incoming_card_message(_Msg(html_text=html)), 89574)

    def test_no_lot_returns_none(self):
        self.assertIsNone(
            _offer_id_from_incoming_card_message(_Msg(html_text="<b>От:</b> a@b.ch"))
        )

    def test_fk_error_is_human(self):
        err = Exception(
            "(sqlalchemy.dialects.postgresql.asyncpg.IntegrityError) "
            "ForeignKeyViolationError Key (resolved_offer_id)=(95142) "
            'is not present in table "offers".'
        )
        msg = _aqua_link_user_error(err)
        self.assertIn("удалён", msg)
        self.assertNotIn("IntegrityError", msg)


class IncomingDeletedOfferBindTests(unittest.IsolatedAsyncioTestCase):
    async def test_sync_does_not_bind_deleted_card_lot(self):
        mail = SimpleNamespace(
            id=1,
            user_id=10,
            from_email="seller@bluewin.ch",
            resolved_offer_id=None,
            mailing_bound=False,
            ad_url="",
            account_email="me@gmail.com",
            subject="Re: iMac",
            from_name="",
            body="",
            product_title="iMac 27",
            offer_price="100",
            photo_url="",
            service_label="",
            outgoing_mail_subject="",
        )
        session = AsyncMock()
        session.get = AsyncMock(return_value=None)
        session.flush = AsyncMock()
        session.rollback = AsyncMock()
        tg = _Msg(html_text="<b>Лот:</b> <code>95142</code>")
        with patch(
            "services.incoming_mail_worker.mail_card_offer_meta",
            new=AsyncMock(return_value=(None, None, None, None, None, None)),
        ):
            await _sync_incoming_mail_offer_with_card(session, mail, tg_message=tg)
        self.assertIsNone(mail.resolved_offer_id)
        session.flush.assert_awaited()


if __name__ == "__main__":
    unittest.main()
