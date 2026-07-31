"""Входящие: validated email продавца и mailing_send_log."""
from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from services.incoming_lead_resolve import resolve_offer_for_incoming_lead


class MailingSendLogResolveTests(unittest.IsolatedAsyncioTestCase):
    async def test_spam_email_without_send_log_gets_no_offer(self):
        session = AsyncMock()
        with patch(
            "services.incoming_lead_resolve.is_incoming_seller_lead",
            new=AsyncMock(return_value=False),
        ):
            off, link, how, snap = await resolve_offer_for_incoming_lead(
                session,
                user_id=1,
                contact_email="enews@my.uniqlo.com",
                subject="Take a Sneak Peek",
            )
        self.assertIsNone(off)
        self.assertFalse(snap.get("mailing_bound"))

    async def test_validated_email_without_send_log_resolves_offer(self):
        flyer = SimpleNamespace(
            id=88001,
            title="FLYER C8.1 NextG 14",
            link="https://www.ricardo.ch/de/a/flyer/",
            raw_json='{"item_title":"FLYER C8.1 NextG 14","item_link":"https://www.ricardo.ch/de/a/flyer/"}',
            price="100",
            photo="https://img.example/flyer.jpg",
        )
        session = AsyncMock()
        with patch(
            "services.incoming_lead_resolve.is_incoming_seller_lead",
            new=AsyncMock(return_value=True),
        ), patch(
            "services.incoming_lead_resolve.has_mailing_send_for_contact",
            new=AsyncMock(return_value=False),
        ), patch(
            "services.incoming_lead_resolve.resolve_inbound_from_send_log",
            new=AsyncMock(return_value=(None, "", "", "")),
        ), patch(
            "services.incoming_lead_resolve.resolve_offer_from_validated_seller_email",
            new=AsyncMock(
                return_value=(flyer, "https://www.ricardo.ch/de/a/flyer/", "validated_seller_email")
            ),
        ), patch(
            "services.incoming_lead_resolve._load_conversation_link",
            new=AsyncMock(return_value=None),
        ), patch(
            "services.incoming_lead_resolve._resolve_outgoing_subject",
            new=AsyncMock(return_value="Interesse an FLYER C8.1 NextG 14"),
        ):
            off, link, how, snap = await resolve_offer_for_incoming_lead(
                session,
                user_id=1,
                contact_email="siwaelti@icloud.com",
                subject="Re: FLYER C8.1 NextG 14 - noch da?",
                inbox_email="buyer@gmail.com",
            )
        self.assertIs(off, flyer)
        self.assertTrue(snap.get("mailing_bound"))
        self.assertEqual(snap.get("product_title"), "FLYER C8.1 NextG 14")

    async def test_resolves_from_send_log_when_mailed(self):
        shoes = SimpleNamespace(
            id=10,
            title="Herren Gucci Schuhe",
            link="https://www.ricardo.ch/de/a/shoes/",
            raw_json="{}",
            price="80 .-",
            photo="https://img.example/shoes.jpg",
        )
        session = AsyncMock()
        with patch(
            "services.incoming_lead_resolve.is_incoming_seller_lead",
            new=AsyncMock(return_value=True),
        ), patch(
            "services.incoming_lead_resolve.has_mailing_send_for_contact",
            new=AsyncMock(return_value=True),
        ), patch(
            "services.incoming_lead_resolve.resolve_inbound_from_send_log",
            new=AsyncMock(
                return_value=(
                    shoes,
                    "https://www.ricardo.ch/de/a/shoes/",
                    "Interesse an Herren Gucci Schuhe",
                    "mailing_send_log",
                )
            ),
        ), patch(
            "services.incoming_lead_resolve._load_conversation_link",
            new=AsyncMock(return_value=None),
        ):
            off, link, how, snap = await resolve_offer_for_incoming_lead(
                session,
                user_id=1,
                contact_email="noriko3@bluewin.ch",
                subject="Re: Interesse an Herren Gucci Schuhe",
                inbox_email="buyer@gmail.com",
            )
        self.assertIs(off, shoes)
        self.assertEqual(snap.get("product_title"), "Herren Gucci Schuhe")
        self.assertTrue(snap.get("mailing_bound"))

    async def test_follow_up_uses_incoming_dialog_when_send_log_empty(self):
        bike = SimpleNamespace(
            id=77302,
            title="Cilo Renner",
            link="https://www.ricardo.ch/de/a/1325645142/",
            raw_json="{}",
            price="1 .-",
            photo="https://img.example/bike.jpg",
        )
        session = AsyncMock()
        with patch(
            "services.incoming_lead_resolve.is_incoming_seller_lead",
            new=AsyncMock(return_value=True),
        ), patch(
            "services.incoming_lead_resolve.has_mailing_send_for_contact",
            new=AsyncMock(return_value=True),
        ), patch(
            "services.incoming_lead_resolve.resolve_inbound_from_send_log",
            new=AsyncMock(return_value=(None, "", "", "")),
        ), patch(
            "services.incoming_lead_resolve.resolve_offer_from_validated_seller_email",
            new=AsyncMock(return_value=(None, "", "")),
        ), patch(
            "services.incoming_lead_resolve._load_conversation_link",
            new=AsyncMock(return_value=None),
        ), patch(
            "services.incoming_lead_resolve.find_offer_from_incoming_dialog",
            new=AsyncMock(return_value=(bike, "incoming_dialog")),
        ), patch(
            "services.incoming_lead_resolve._resolve_outgoing_subject",
            new=AsyncMock(return_value="Frage zu Cilo Renner"),
        ):
            off, link, how, snap = await resolve_offer_for_incoming_lead(
                session,
                user_id=1,
                contact_email="raepper@gmx.ch",
                subject="Aw: Re: Aw: Frage zu Cilo",
                inbox_email="buyer@gmail.com",
            )
        self.assertIs(off, bike)
        self.assertIn("ricardo.ch", link)
        self.assertEqual(how, "incoming_dialog")
        self.assertTrue(snap.get("mailing_bound"))


if __name__ == "__main__":
    unittest.main()
