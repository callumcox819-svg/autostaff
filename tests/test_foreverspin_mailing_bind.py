import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from services.strict_seller_bind import resolve_strict_seller_inbound_offer


class ForeverspinMailingBindTests(unittest.IsolatedAsyncioTestCase):
    async def test_mailing_log_wins_over_stale_validated_on_same_email(self):
        """Re: с OFFER — лот из /send, даже если OfferEmail указывает на другой лот."""
        hemnes = SimpleNamespace(
            id=91520,
            title="Frisiertisch Hemnes Ikea",
            link="https://www.ricardo.ch/de/a/h/",
            raw_json="{}",
            price="20",
            photo="",
        )
        kreisel = SimpleNamespace(
            id=92001,
            title="Damast Stahl Kreisel von Foreverspin",
            link="https://www.ricardo.ch/de/a/k/",
            raw_json='{"item_title":"Damast Stahl Kreisel von Foreverspin","item_link":"https://www.ricardo.ch/de/a/k/"}',
            price="45",
            photo="https://img.example/k.jpg",
        )
        session = AsyncMock()
        subj = "Re: Noch verfügbar? Damast Stahl Kreisel von Foreverspin"

        with patch(
            "services.strict_seller_bind._offers_from_offer_email_rows",
            new=AsyncMock(return_value=[hemnes]),
        ), patch(
            "services.strict_seller_bind._mailing_log_rows_for_recipient",
            new=AsyncMock(return_value=[]),
        ), patch(
            "services.strict_seller_bind.find_offer_from_mailing_log",
            new=AsyncMock(return_value=(kreisel, "mailing_product_thread")),
        ):
            off, how = await resolve_strict_seller_inbound_offer(
                session,
                1,
                "ablarer@gmx.ch",
                subject=subj,
            )

        self.assertIs(off, kreisel)
        self.assertTrue(how)


if __name__ == "__main__":
    unittest.main()
