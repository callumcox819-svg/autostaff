import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from services.incoming_validated_offer import resolve_inbound_by_validated_email


class StrictOneEmailOneLotTests(unittest.IsolatedAsyncioTestCase):
    async def test_multiple_offer_email_rows_no_guess(self):
        a = object()
        b = object()
        session = AsyncMock()
        with patch(
            "services.offer_storage.list_offers_for_validated_contact_email",
            new=AsyncMock(return_value=[a, b]),
        ), patch(
            "services.offer_storage.find_single_offer_for_seller_contact_email",
            new=AsyncMock(return_value=None),
        ):
            off, how = await resolve_inbound_by_validated_email(
                session, 1, "gnimor@gmx.ch", subject="Re: Adidas"
            )
        self.assertIsNone(off)
        self.assertEqual(how, "")


if __name__ == "__main__":
    unittest.main()
