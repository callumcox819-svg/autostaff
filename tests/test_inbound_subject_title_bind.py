import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from services.incoming_lead_resolve import resolve_offer_for_incoming_lead


class SubjectTitleInboundBindTests(unittest.IsolatedAsyncioTestCase):
    async def test_subject_title_db_when_no_mailing_log(self):
        bed = SimpleNamespace(
            id=88001,
            title="Kinderbett Massivholz, Qualitätsmatratze, abziehbar wie neu",
            raw_json='{"item_title":"Kinderbett Massivholz, Qualitätsmatratze, abziehbar wie neu","item_link":"https://ricardo.ch/k","item_price":"120"}',
            link="https://ricardo.ch/k",
            price="120",
            photo="https://img.example/bed.jpg",
        )
        session = AsyncMock()
        subj = "RE: Interesse an Kinderbett Massivholz, Qualitätsmatratze, abziehbar wie neu"

        with patch(
            "services.offer_storage.pick_offer_for_incoming_reply",
            new=AsyncMock(return_value=None),
        ), patch(
            "services.incoming_lead_resolve._resolve_offer_from_mailing_thread",
            new=AsyncMock(return_value=(None, "")),
        ), patch(
            "services.incoming_validated_offer.resolve_inbound_by_validated_email",
            new=AsyncMock(return_value=(None, "")),
        ), patch(
            "services.incoming_lead_resolve.prior_resolved_offer_id_for_seller",
            new=AsyncMock(return_value=None),
        ), patch(
            "services.offer_storage.find_offer_for_mailed_seller_reply",
            new=AsyncMock(return_value=None),
        ), patch(
            "services.offer_storage.find_offer_by_product_title_in_subject",
            new=AsyncMock(return_value=bed),
        ):
            off, link, how, snap = await resolve_offer_for_incoming_lead(
                session,
                user_id=1,
                contact_email="joegabi@bluewin.ch",
                subject=subj,
                inbox_email="juvedeqa932@gmail.com",
            )
        self.assertIs(off, bed)
        self.assertEqual(how, "subject_title_db")
        self.assertIn("Kinderbett", snap.get("product_title") or "")


if __name__ == "__main__":
    unittest.main()
