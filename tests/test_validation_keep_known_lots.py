import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from services.offer_storage import save_all_offers_from_import


class ValidationKeepKnownLotsTests(unittest.IsolatedAsyncioTestCase):
    async def test_zero_new_emails_still_exports_existing_lot(self):
        existing = SimpleNamespace(
            id=42,
            person_name="Hans Mueller",
            title="Sofa",
            price="100",
            link="https://www.ricardo.ch/de/a/abc/",
            photo="",
            raw_json=json.dumps(
                {
                    "item_link": "https://www.ricardo.ch/de/a/abc/",
                    "item_title": "Sofa",
                    "item_person_name": "Hans Mueller",
                    "validated_emails": ["hans@example.com"],
                },
                ensure_ascii=False,
            ),
        )
        result = MagicMock()
        result.scalars.return_value.all.return_value = [existing]
        session = AsyncMock()
        session.execute = AsyncMock(return_value=result)
        session.flush = AsyncMock()

        with patch(
            "services.offer_storage.load_user_validated_email_keys",
            new=AsyncMock(return_value={"hans@example.com"}),
        ):
            saved, with_email, email_rows, output = await save_all_offers_from_import(
                session,
                user_id=1,
                items=[
                    {
                        "item_person_name": "Hans Mueller",
                        "item_link": "https://www.ricardo.ch/de/a/abc/",
                        "item_title": "Sofa",
                    }
                ],
                validated_rows=[],
                norm_email=lambda e: (e or "").strip().lower(),
            )

        self.assertEqual(saved, 0)
        self.assertEqual(with_email, 0)
        self.assertEqual(email_rows, 0)
        self.assertEqual(len(output), 1)
        self.assertEqual(output[0]["offer_id"], 42)
        self.assertEqual(output[0]["validated_emails"], ["hans@example.com"])

    async def test_reset_restores_offer_email_from_raw(self):
        from models import OfferEmail

        existing = SimpleNamespace(
            id=42,
            person_name="Hans Mueller",
            title="Sofa",
            price="100",
            link="https://www.ricardo.ch/de/a/abc/",
            photo="",
            raw_json=json.dumps(
                {
                    "item_link": "https://www.ricardo.ch/de/a/abc/",
                    "item_title": "Sofa",
                    "item_person_name": "Hans Mueller",
                    "validated_emails": ["hans@example.com"],
                },
                ensure_ascii=False,
            ),
        )
        result = MagicMock()
        result.scalars.return_value.all.return_value = [existing]
        added: list = []
        session = AsyncMock()
        session.execute = AsyncMock(return_value=result)
        session.flush = AsyncMock()
        session.add = added.append

        with patch(
            "services.offer_storage.load_user_validated_email_keys",
            new=AsyncMock(return_value=set()),
        ):
            saved, with_email, email_rows, output = await save_all_offers_from_import(
                session,
                user_id=1,
                items=[
                    {
                        "item_person_name": "Hans Mueller",
                        "item_link": "https://www.ricardo.ch/de/a/abc/",
                        "item_title": "Sofa",
                    }
                ],
                validated_rows=[],
                norm_email=lambda e: (e or "").strip().lower(),
                skip_queue_emails={"hans@example.com"},
            )

        self.assertEqual(saved, 0)
        self.assertGreaterEqual(email_rows, 1)
        self.assertGreaterEqual(with_email, 1)
        self.assertTrue(any(isinstance(x, OfferEmail) for x in added))
        self.assertEqual(len(output), 1)
        self.assertEqual(output[0]["offer_id"], 42)

    async def test_new_valid_email_is_not_dropped_without_existing_lot(self):
        added: list = []

        def _add(obj):
            added.append(obj)
            if getattr(obj, "id", None) is None:
                obj.id = 77

        result = MagicMock()
        result.scalars.return_value.all.return_value = []
        session = AsyncMock()
        session.execute = AsyncMock(return_value=result)
        session.flush = AsyncMock()
        session.add = _add

        item = {
            "item_person_name": "New Seller",
            "item_link": "https://www.ricardo.ch/de/a/new/",
            "item_title": "MacBook",
        }
        with patch(
            "services.offer_storage.load_user_validated_email_keys",
            new=AsyncMock(return_value={"old@example.com"}),
        ), patch(
            "services.offer_storage.strip_validated_email_from_other_offers",
            new=AsyncMock(),
        ):
            saved, with_email, email_rows, output = await save_all_offers_from_import(
                session,
                user_id=1,
                items=[item],
                validated_rows=[
                    {
                        "raw": item,
                        "emails": ["new.seller@bluewin.ch"],
                    }
                ],
                norm_email=lambda e: (e or "").strip().lower(),
                skip_queue_emails={"new.seller@bluewin.ch"},
            )

        self.assertEqual(saved, 1)
        self.assertEqual(with_email, 1)
        self.assertGreaterEqual(email_rows, 1)
        self.assertTrue(output)


if __name__ == "__main__":
    unittest.main()
