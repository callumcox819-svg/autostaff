import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from services.incoming_offer_bind import force_bind_incoming_seller_offer


class ForceBindIncomingTests(unittest.IsolatedAsyncioTestCase):
    async def test_subject_needle_in_mailed_pool(self):
        stickers = SimpleNamespace(
            id=901,
            user_id=1,
            title="L116 - Stickers Mania - Les couleurs",
            link="https://www.ricardo.ch/de/a/1/",
            raw_json='{"item_title":"L116 - Stickers Mania","item_link":"https://www.ricardo.ch/de/a/1/"}',
            price="10",
            photo="https://img.example/x.jpg",
        )
        session = AsyncMock()

        async def _resolve_empty(*_a, **_k):
            return None, "", "", {}

        async def _mailed_empty(*_a, **_k):
            return None

        with patch(
            "services.strict_seller_bind.resolve_strict_seller_inbound_offer",
            new=AsyncMock(return_value=(None, "")),
        ), patch(
            "services.incoming_offer_bind.resolve_offer_for_incoming_lead",
            new=AsyncMock(side_effect=_resolve_empty),
        ), patch(
            "services.incoming_offer_bind._offer_from_prior_inbound_mail",
            new=AsyncMock(return_value=None),
        ), patch(
            "services.incoming_offer_bind.find_offer_for_mailed_seller_reply",
            new=AsyncMock(return_value=None),
        ), patch(
            "services.mailing_send_log.has_mailing_send_for_contact",
            new=AsyncMock(return_value=False),
        ), patch(
            "services.incoming_offer_bind.list_offers_for_validated_contact_email",
            new=AsyncMock(return_value=[]),
        ), patch(
            "services.mailing_send_log.list_offers_from_mailing_log",
            new=AsyncMock(return_value=[stickers]),
        ), patch(
            "services.mailing_send_log.list_allowed_offers_for_incoming_contact",
            new=AsyncMock(return_value=[]),
        ), patch(
            "services.mailing_send_log.find_offer_from_send_log_by_product_context",
            new=AsyncMock(return_value=(None, "")),
        ):
            off, link, how, snap = await force_bind_incoming_seller_offer(
                session,
                user_id=1,
                contact_email="locepa@bluewin.ch",
                subject="Re: Noch verfügbar? L116 - Stickers Mania - Les couleurs (+6ans)",
            )

        self.assertIs(off, stickers)
        self.assertIn("ricardo.ch", link)
        self.assertEqual(how, "mailing_log_force")
        self.assertIn("Stickers", snap.get("product_title", ""))


if __name__ == "__main__":
    unittest.main()
