import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from services.offer_storage import marketplace_service_label_from_link, pick_offer_for_incoming_reply


class Work88InboundPickTests(unittest.IsolatedAsyncioTestCase):
    async def test_one_validated_email_returns_that_lot(self):
        off = SimpleNamespace(
            id=95142,
            title="Apple iMac 27",
            raw_json="{}",
            link="https://ricardo.ch/a/1",
        )
        with patch(
            "services.offer_storage.list_offers_for_validated_contact_email",
            new=AsyncMock(return_value=[off]),
        ):
            got = await pick_offer_for_incoming_reply(
                AsyncMock(),
                user_id=1,
                from_email="tolgasevencan@icloud.com",
                subject="Aw: Kurze Anfrage zu Apple iMac 27",
            )
        self.assertIs(got, off)

    def test_kleinanzeigen_and_ricardo_labels(self):
        self.assertEqual(
            marketplace_service_label_from_link("https://www.kleinanzeigen.de/s-anzeige/x"),
            "Kleinanzeigen",
        )
        self.assertEqual(
            marketplace_service_label_from_link("https://www.ricardo.ch/de/a/1/"),
            "ricardo.ch",
        )


if __name__ == "__main__":
    unittest.main()
