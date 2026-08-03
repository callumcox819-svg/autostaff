import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from services.incoming_lead_resolve import (
    inbound_thread_binds_offer,
    resolve_offer_for_incoming_lead,
)


class InboundSubjectOverEmailTests(unittest.IsolatedAsyncioTestCase):
    def test_thread_rejects_gta_when_subject_is_work_light(self):
        gta = SimpleNamespace(
            id=92656,
            title="Grand Theft Auto V - PS4",
            raw_json='{"item_title":"Grand Theft Auto V - PS4"}',
        )
        subj = "RE: Guten Tag, Arbeitsleuchte 360° LED 12000 Lumen noch verfügbar?"
        self.assertFalse(inbound_thread_binds_offer(subj, "", gta))

    def test_weak_reply_still_trusts_offer(self):
        gta = SimpleNamespace(
            id=92656,
            title="Grand Theft Auto V - PS4",
            raw_json='{"item_title":"Grand Theft Auto V - PS4"}',
        )
        self.assertTrue(inbound_thread_binds_offer("Re: Aw:", "Ja\nDanke", gta))

    async def test_mailing_log_wins_over_mismatched_validated_email(self):
        gta = SimpleNamespace(id=92656, title="Grand Theft Auto V - PS4", raw_json="{}")
        lamp = SimpleNamespace(
            id=91001,
            title="Arbeitsleuchte 360° LED 12000 Lumen",
            raw_json='{"item_title":"Arbeitsleuchte 360° LED 12000 Lumen","item_link":"https://ricardo.ch/x"}',
            link="https://ricardo.ch/x",
        )
        session = AsyncMock()
        subj = "RE: Guten Tag, Arbeitsleuchte 360° LED 12000 Lumen noch verfügbar?"

        with patch(
            "services.incoming_validated_offer.resolve_inbound_by_validated_email",
            new=AsyncMock(return_value=(gta, "validated_email_one_lot")),
        ), patch(
            "services.incoming_lead_resolve._resolve_offer_from_mailing_thread",
            new=AsyncMock(return_value=(lamp, "mailing_log_subject")),
        ):
            off, _link, how, snap = await resolve_offer_for_incoming_lead(
                session,
                user_id=1,
                contact_email="sattelschrank@bluewin.ch",
                subject=subj,
            )
        self.assertIs(off, lamp)
        self.assertEqual(how, "mailing_log_subject")
        self.assertIn("Arbeitsleuchte", snap.get("product_title") or "")


if __name__ == "__main__":
    unittest.main()
