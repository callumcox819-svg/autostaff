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


if __name__ == "__main__":
    unittest.main()
