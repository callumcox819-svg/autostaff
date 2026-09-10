import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from services.aqua_profiles import AquaProfile, _parse_profile_item
from services.html_reply import build_offer_html_ctx


class GooProfileParseTests(unittest.TestCase):
    def test_parse_buyer_and_address(self):
        p = _parse_profile_item(
            {
                "profileID": "NhAfL6NpU8o",
                "title": "NL home",
                "fullName": "Maria Zeglier",
                "address": "Keizersgracht 1, Amsterdam",
            }
        )
        self.assertIsNotNone(p)
        assert p is not None
        self.assertEqual(p.profile_id, "NhAfL6NpU8o")
        self.assertEqual(p.full_name, "Maria Zeglier")
        self.assertIn("Amsterdam", p.address)


class HtmlCtxBuyerTests(unittest.IsolatedAsyncioTestCase):
    async def test_uses_evoleum_profile_not_stale_local(self):
        session = AsyncMock()
        session.get = AsyncMock(return_value=SimpleNamespace(id=1))
        offer = SimpleNamespace(
            id=10,
            title="",
            price="",
            photo="",
            raw_json='{"item_title":"Philips 3200","item_price":"225","item_photo":"https://img.test/p.jpg"}',
            user_id=1,
        )
        mail = SimpleNamespace(
            resolved_offer_id=10,
            product_title="",
            offer_price="",
            photo_url="",
        )
        exec_offer = MagicMock()
        exec_offer.scalars.return_value.first.return_value = offer
        session.execute = AsyncMock(return_value=exec_offer)

        with patch(
            "services.aqua_keys.resolve_html_buyer_profile",
            new=AsyncMock(return_value=("Maria Zeglier", "Keizersgracht 1, Amsterdam")),
        ):
            ctx = await build_offer_html_ctx(
                session, 1, "seller@hotmail.com", link="https://x.test/l", mail=mail
            )
        self.assertEqual(ctx["BUYER_NAME"], "Maria Zeglier")
        self.assertIn("Amsterdam", ctx["ADDRESS"])
        self.assertEqual(ctx["ITEM_TITLE"], "Philips 3200")
        self.assertIn("225", ctx["PRICE"])
        self.assertIn("img.test", ctx["IMAGE_URL"])

    async def test_stale_local_not_used_when_goo_returns_profile(self):
        from services.aqua_keys import resolve_html_buyer_profile

        session = AsyncMock()
        user = SimpleNamespace(id=1, goo_profile_id="old")
        cfg = SimpleNamespace(
            team_id="evoleum",
            profile_id="NhAfL6NpU8o",
            api_key="u",
            team_key="t",
            service_code="marktplaats_nl",
        )
        prof = AquaProfile(
            profile_id="NhAfL6NpU8o",
            title="",
            full_name="Maria Zeglier",
            address="Damrak 9, Amsterdam",
        )
        with (
            patch(
                "services.api_teams.get_selected_team_config",
                new=AsyncMock(return_value=cfg),
            ),
            patch(
                "services.aqua_keys.get_user_profile_buyer_name",
                new=AsyncMock(return_value="Anna Kerginer"),
            ),
            patch(
                "services.aqua_keys.get_user_profile_address",
                new=AsyncMock(return_value="Panoramastrasse 11, Hergiswil"),
            ),
            patch(
                "services.aqua_profiles.find_goo_profile_by_id",
                new=AsyncMock(return_value=prof),
            ),
            patch(
                "services.aqua_keys.apply_aqua_profile_to_user",
                new=AsyncMock(),
            ),
            patch(
                "services.aqua_keys.set_user_setting",
                new=AsyncMock(),
            ),
        ):
            session.commit = AsyncMock()
            name, addr = await resolve_html_buyer_profile(session, user)
        self.assertEqual(name, "Maria Zeglier")
        self.assertIn("Amsterdam", addr)
        self.assertNotIn("Anna", name)
        self.assertNotIn("Hergiswil", addr)


if __name__ == "__main__":
    unittest.main()
