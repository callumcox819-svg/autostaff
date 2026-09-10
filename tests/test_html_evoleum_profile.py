import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from services.html_reply import _format_eur_price, _pick_non_zero_price, build_offer_html_ctx


class HtmlPriceFormatTests(unittest.TestCase):
    def test_zero_price_empty(self):
        self.assertEqual(_format_eur_price("0"), "")
        self.assertEqual(_format_eur_price("0 €"), "")
        self.assertEqual(_format_eur_price("EUR 0"), "")

    def test_normal_price(self):
        self.assertEqual(_format_eur_price("55"), "EUR 55")
        self.assertEqual(_format_eur_price("55.00 EUR"), "EUR 55.00")

    def test_pick_prefers_nonzero(self):
        self.assertEqual(_pick_non_zero_price("0 €", "55.00 EUR"), "EUR 55.00")


class HtmlCtxBuyerTests(unittest.IsolatedAsyncioTestCase):
    async def test_uses_local_html_profile_fields(self):
        session = AsyncMock()
        session.get = AsyncMock(return_value=SimpleNamespace(id=1))
        offer = SimpleNamespace(
            id=10,
            title="",
            price="55.00 EUR",
            photo="",
            raw_json='{"item_title":"Philips 3200","item_price":"55.00 EUR","item_photo":"https://img.test/p.jpg"}',
            user_id=1,
        )
        mail = SimpleNamespace(
            resolved_offer_id=10,
            product_title="",
            offer_price="55.00 EUR",
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
        self.assertIn("55", ctx["PRICE"])
        self.assertNotIn("EUR 0", ctx["PRICE"])
        self.assertIn("img.test", ctx["IMAGE_URL"])

    async def test_bound_mismatch_clears_stale(self):
        from services.aqua_keys import resolve_html_buyer_profile

        session = AsyncMock()
        user = SimpleNamespace(id=1, goo_profile_id="OLD")
        cfg = SimpleNamespace(team_id="evoleum", profile_id="NhAfL6NpU8o")
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
                new=AsyncMock(return_value="Panoramastrasse 11"),
            ),
        ):
            name, addr = await resolve_html_buyer_profile(session, user)
        self.assertEqual(name, "")
        self.assertEqual(addr, "")


if __name__ == "__main__":
    unittest.main()
