import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from services.strict_seller_bind import resolve_strict_seller_inbound_offer


class StrictSellerBindTests(unittest.IsolatedAsyncioTestCase):
    async def test_single_mailing_log_offer(self):
        sofa = SimpleNamespace(
            id=91168,
            title="Micasa 2er Sofa",
            link="https://www.ricardo.ch/de/a/1/",
            raw_json='{"item_title":"Micasa 2er Sofa","item_link":"https://www.ricardo.ch/de/a/1/"}',
            price="249",
            photo="",
        )
        session = AsyncMock()
        with patch(
            "services.strict_seller_bind._offers_from_offer_email_rows",
            new=AsyncMock(return_value=[sofa]),
        ), patch(
            "services.strict_seller_bind._mailing_log_rows_for_recipient",
            new=AsyncMock(return_value=[(SimpleNamespace(mail_subject="Kurze Anfrage zu Micasa 2er Sofa"), sofa)]),
        ):
            off, how = await resolve_strict_seller_inbound_offer(
                session,
                1,
                "zen.kitzelt2y@icloud.com",
                subject="Re: Kurze Anfrage zu Micasa 2er Sofa",
            )
        self.assertIs(off, sofa)
        self.assertIn("strict", how)

    async def test_multiple_mailing_requires_subject_not_sofa_word(self):
        a = SimpleNamespace(id=1, title="Micasa 2er Sofa", raw_json="{}", link="https://a", price="", photo="")
        b = SimpleNamespace(id=2, title="IKEA Sofa bed", raw_json="{}", link="https://b", price="", photo="")
        session = AsyncMock()
        with patch(
            "services.strict_seller_bind._offers_from_offer_email_rows",
            new=AsyncMock(return_value=[]),
        ), patch(
            "services.strict_seller_bind._mailing_log_rows_for_recipient",
            new=AsyncMock(
                return_value=[
                    (SimpleNamespace(mail_subject="Frage A"), a),
                    (SimpleNamespace(mail_subject="Frage B"), b),
                ]
            ),
        ), patch(
            "services.strict_seller_bind.find_offer_from_mailing_log",
            new=AsyncMock(return_value=(None, "")),
        ):
            off, how = await resolve_strict_seller_inbound_offer(
                session,
                1,
                "seller@test.ch",
                subject="Noch zu haben",
                body_text="ist Sofa noch da?",
            )
        self.assertIsNone(off)
        self.assertEqual(how, "")


if __name__ == "__main__":
    unittest.main()
