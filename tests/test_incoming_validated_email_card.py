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
            "services.offer_storage.list_offers_for_validated_contact_email",
            new=AsyncMock(return_value=[adidas]),
        ):
            off, how = await resolve_inbound_by_validated_email(
                session, 1, "gnimor@gmx.ch"
            )
        self.assertIs(off, adidas)
        self.assertEqual(how, "validated_email_one_lot")

    async def test_one_lot_binds_on_guten_tag_subject(self):
        printer = SimpleNamespace(
            id=88002,
            title="Laserdrucker Canon i-SENSYS MF9280Cdn",
            raw_json='{"item_title":"Laserdrucker Canon i-SENSYS MF9280Cdn","validated_emails":["mister_@gmx.ch"],"item_link":"https://www.ricardo.ch/de/a/1/"}',
            price="120",
            link="https://www.ricardo.ch/de/a/1/",
            photo="https://img.example/p.jpg",
        )
        session = AsyncMock()
        with patch(
            "services.offer_storage.list_offers_for_validated_contact_email",
            new=AsyncMock(return_value=[printer]),
        ):
            off, how = await resolve_inbound_by_validated_email(
                session,
                1,
                "mister_@gmx.ch",
                subject='Aw: Guten Tag, Laserdrucker Canon i-SENSYS MF9280Cdn " noch verfügbar?',
            )
        self.assertIs(off, printer)
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

    def test_snapshot_has_service_price_photo(self):
        from services.incoming_validated_offer import offer_inbound_snapshot

        off = SimpleNamespace(
            title="Laserdrucker Canon",
            price="90",
            photo="https://img.example/p.jpg",
            link="https://www.ricardo.ch/de/a/1/",
            raw_json="{}",
        )
        snap = offer_inbound_snapshot(off)
        self.assertEqual(snap["service_label"], "ricardo.ch")
        self.assertEqual(snap["offer_price"], "90")
        self.assertEqual(snap["photo_url"], "https://img.example/p.jpg")

    def test_card_keeps_lot_fields_without_offer_id(self):
        from services.incoming_mail_worker import render_mail_text_chunks

        html = render_mail_text_chunks(
            account_email="anna@gmail.com",
            from_name="mister",
            from_email="mister_@gmx.ch",
            subject="Aw: x",
            body="Ja ist zu haben",
            offer_id=None,
            product_title="Laserdrucker Canon i-SENSYS",
            offer_price="120",
            service_label="ricardo.ch",
        )[0]
        self.assertIn("Laserdrucker Canon", html)
        self.assertIn("120", html)
        self.assertIn("ricardo.ch", html)


if __name__ == "__main__":
    unittest.main()
