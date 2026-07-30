"""Входящие: лот по validated email, не по теме Re:."""
from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from services.incoming_lead_resolve import _resolve_from_validated_seller_email


class ValidatedEmailOfferResolveTests(unittest.IsolatedAsyncioTestCase):
    async def test_single_validated_email_returns_offer_without_subject(self):
        from types import SimpleNamespace

        chair = SimpleNamespace(
            id=10,
            title="Armlehnstuhl Taormina",
            link="https://www.ricardo.ch/de/a/chair/",
            raw_json="{}",
        )
        session = AsyncMock()
        with patch(
            "services.incoming_lead_resolve.list_offers_for_validated_contact_email",
            new=AsyncMock(return_value=[chair]),
        ):
            off, link, how = await _resolve_from_validated_seller_email(
                session,
                user_id=1,
                contact_email="massi38@icloud.com",
            )
        self.assertIs(off, chair)
        self.assertIn("chair", link)
        self.assertEqual(how, "validated_email")


if __name__ == "__main__":
    unittest.main()
