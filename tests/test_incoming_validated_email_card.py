import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from services.incoming_validated_offer import (
    inbound_card_inbox_label,
    resolve_inbound_by_validated_email,
    seller_person_name,
)


class ValidatedEmailInboundTests(unittest.IsolatedAsyncioTestCase):
    async def test_one_offer_email_returns_lot(self):
        adidas = SimpleNamespace(
            id=91660,
            title="Adidas Runfalcon 5 Laufschuhe Gr 42   NEU",
            raw_json='{"item_title":"Adidas Runfalcon 5 Laufschuhe Gr 42   NEU","item_person_name":"Gnimor","validated_emails":["gnimor@gmx.ch"]}',
            price="40",
            link="https://www.ricardo.ch/de/a/1325931184/",
            photo="https://img.example/x.jpg",
        )
        session = AsyncMock()
        with patch(
            "services.incoming_validated_offer._offers_from_offer_email_rows",
            new=AsyncMock(return_value=[adidas]),
        ):
            off, how = await resolve_inbound_by_validated_email(
                session, 1, "gnimor@gmx.ch"
            )
        self.assertIs(off, adidas)
        self.assertEqual(how, "validated_email_one_lot")

    def test_inbox_label_seller_and_buyer(self):
        off = SimpleNamespace(
            raw_json='{"item_person_name":"Gnimor"}',
            person_name="Gnimor",
        )
        self.assertEqual(
            inbound_card_inbox_label(off, buyer_display_name="Anna Kerher"),
            "Gnimor (Anna Kerher)",
        )
        self.assertEqual(seller_person_name(off), "Gnimor")


if __name__ == "__main__":
    unittest.main()
