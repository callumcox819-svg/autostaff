"""Входящие: приоритет mailing_send_log."""
from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from services.incoming_lead_resolve import resolve_offer_for_incoming_lead


class MailingSendLogResolveTests(unittest.IsolatedAsyncioTestCase):
    async def test_resolves_from_send_log_first(self):
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
        self.assertEqual(snap.get("outgoing_mail_subject"), "Interesse an Herren Gucci Schuhe")
        self.assertEqual(how, "mailing_send_log")


if __name__ == "__main__":
    unittest.main()
