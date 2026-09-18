import unittest
from unittest.mock import AsyncMock, patch

from handlers.templates import TemplateItem, _mailing_text_pool


class MailingPresetPriorityTests(unittest.IsolatedAsyncioTestCase):
    async def test_smart_presets_exclude_regular_presets(self):
        with (
            patch(
                "handlers.templates.load_smart_texts",
                AsyncMock(return_value=["Smart OFFER {{SENDER_NAME}}"]),
            ),
            patch(
                "handlers.templates.load_templates",
                AsyncMock(return_value=[TemplateItem("Old", "Old regular OFFER")]),
            ),
        ):
            pool = await _mailing_text_pool(123)

        self.assertEqual(pool, ["Smart OFFER {{SENDER_NAME}}"])

    async def test_regular_presets_are_fallback_when_smart_list_empty(self):
        with (
            patch("handlers.templates.load_smart_texts", AsyncMock(return_value=[])),
            patch(
                "handlers.templates.load_templates",
                AsyncMock(return_value=[TemplateItem("Fallback", "Regular OFFER")]),
            ),
        ):
            pool = await _mailing_text_pool(123)

        self.assertEqual(pool, ["Regular OFFER"])


if __name__ == "__main__":
    unittest.main()
