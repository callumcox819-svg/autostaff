import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from services.html_reply import (
    _format_eur_price,
    _format_html_price,
    _pick_non_zero_price,
    build_offer_html_ctx,
)
from services.html_spoof import apply_nick_to_html
from services.placeholders import apply_placeholders


class HtmlPriceFormatTests(unittest.TestCase):
    def test_zero_price_empty(self):
        self.assertEqual(_format_eur_price("0"), "")
        self.assertEqual(_format_eur_price("0 €"), "")
        self.assertEqual(_format_eur_price("EUR 0"), "")

    def test_normal_price(self):
        self.assertEqual(_format_eur_price("55"), "EUR 55")
        self.assertEqual(_format_eur_price("55.00 EUR"), "EUR 55.00")

    def test_ch_price_is_chf(self):
        self.assertEqual(_format_html_price("40", currency="CHF"), "CHF 40")
        self.assertEqual(_format_html_price("40 .-", currency="CHF"), "CHF 40.-")
        self.assertEqual(_format_html_price("EUR 40", currency="CHF"), "CHF 40.00")

    def test_hu_price_is_forint(self):
        from services.html_reply import _html_currency_for_country

        self.assertEqual(_html_currency_for_country("hu"), "HUF")
        self.assertEqual(_html_currency_for_country("hr"), "EUR")
        self.assertEqual(_format_html_price("155 000 Ft", currency="HUF"), "155 000 Ft")
        self.assertEqual(_format_html_price("155000", currency="HUF"), "155 000 Ft")
        self.assertEqual(_format_html_price("155 000 Ft", currency="EUR"), "155 000 Ft")
        self.assertEqual(
            _pick_non_zero_price("EUR 155", "155 000 Ft", currency="HUF"),
            "155 000 Ft",
        )

    def test_pick_prefers_nonzero(self):
        self.assertEqual(_pick_non_zero_price("0 €", "55.00 EUR"), "EUR 55.00")
        self.assertEqual(
            _pick_non_zero_price("0", "40", currency="CHF"),
            "CHF 40",
        )


class HtmlSpoofNickTests(unittest.TestCase):
    def test_nick_in_html_and_from_placeholders(self):
        html = "<p>Hi {{NICK}}</p><p>Koper: {{BUYER_NAME}}</p>"
        out = apply_nick_to_html(html, "Lisa Support")
        out = apply_placeholders(out, ctx={"BUYER_NAME": "Maria", "NICK": "Lisa Support"})
        self.assertIn("Lisa Support", out)
        self.assertIn("Maria", out)
        self.assertNotIn("{{NICK}}", out)


class HtmlCountrySubjectTests(unittest.IsolatedAsyncioTestCase):
    async def test_html_reply_keeps_re_subject_even_when_spoofing(self):
        from services.html_reply import get_html_reply_subject

        session = AsyncMock()
        user = SimpleNamespace(id=1)
        with patch(
            "services.html_spoof.is_spoofing_enabled",
            new=AsyncMock(return_value=True),
        ):
            subject = await get_html_reply_subject(
                session, user, fallback="Re: Alte NL-Thema"
            )
        # Spoof theme must not replace Subject — Gmail would split the thread.
        self.assertEqual(subject, "Re: Alte NL-Thema")


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

        with (
            patch(
                "services.aqua_keys.resolve_html_buyer_profile",
                new=AsyncMock(return_value=("Maria Zeglier", "Keizersgracht 1, Amsterdam")),
            ),
            patch(
                "services.html_reply.get_spoof_display_name",
                new=AsyncMock(return_value="Marktplaats Support"),
            ),
            patch(
                "services.enabled_countries.get_active_country",
                new=AsyncMock(return_value="nl"),
            ),
        ):
            ctx = await build_offer_html_ctx(
                session, 1, "seller@hotmail.com", link="https://x.test/l", mail=mail
            )
        self.assertEqual(ctx["BUYER_NAME"], "Maria Zeglier")
        self.assertEqual(ctx["NICK"], "Marktplaats Support")
        self.assertIn("Amsterdam", ctx["ADDRESS"])
        self.assertEqual(ctx["ITEM_TITLE"], "Philips 3200")
        self.assertIn("55", ctx["PRICE"])
        self.assertIn("EUR", ctx["PRICE"])
        self.assertNotIn("EUR 0", ctx["PRICE"])
        self.assertIn("img.test", ctx["IMAGE_URL"])

    async def test_ch_ctx_uses_chf_and_normalizes_image(self):
        session = AsyncMock()
        session.get = AsyncMock(return_value=SimpleNamespace(id=1))
        offer = SimpleNamespace(
            id=10,
            title="",
            price="40",
            photo="",
            raw_json='{"item_title":"KOMPRESSIONS-KNIESTRÜMPFE","item_price":"40","item_photo":"//img.ricardostatic.ch/sock.jpg"}',
            user_id=1,
        )
        mail = SimpleNamespace(
            resolved_offer_id=10,
            product_title="",
            offer_price="40",
            photo_url="",
        )
        exec_offer = MagicMock()
        exec_offer.scalars.return_value.first.return_value = offer
        session.execute = AsyncMock(return_value=exec_offer)

        with (
            patch(
                "services.aqua_keys.resolve_html_buyer_profile",
                new=AsyncMock(
                    return_value=("Anna Gremlis", "Panoramastrasse 11, 6052 Hergiswil")
                ),
            ),
            patch(
                "services.html_reply.get_spoof_display_name",
                new=AsyncMock(return_value="Ricardo Support"),
            ),
            patch(
                "services.enabled_countries.get_active_country",
                new=AsyncMock(return_value="ch"),
            ),
        ):
            ctx = await build_offer_html_ctx(
                session, 1, "seller@bluewin.ch", link="https://x.test/l", mail=mail
            )
        self.assertEqual(ctx["PRICE"], "CHF 40")
        self.assertTrue(ctx["IMAGE_URL"].startswith("https://img.ricardostatic.ch/"))
        self.assertIn("Anna Gremlis", ctx["BUYER_NAME"])

    async def test_country_scoped_profile_ignores_stale_global_binding(self):
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
        self.assertEqual(name, "Anna Kerginer")
        self.assertEqual(addr, "Panoramastrasse 11")

    async def test_hustle_html_uses_team_name_address(self):
        from services.aqua_keys import resolve_html_buyer_profile

        session = AsyncMock()
        user = SimpleNamespace(id=1)
        cfg = SimpleNamespace(team_id="hustle", profile_id="")

        async def _field(_s, _u, _tid, field):
            return {"buyer_name": "Anna Gremlis", "address": "Musterstraße 12, Berlin"}.get(field, "")

        with (
            patch(
                "services.api_teams.get_selected_team_config",
                new=AsyncMock(return_value=cfg),
            ),
            patch(
                "services.api_teams.get_team_field",
                new=_field,
            ),
        ):
            name, addr = await resolve_html_buyer_profile(session, user)
        self.assertEqual(name, "Anna Gremlis")
        self.assertIn("Berlin", addr)

    async def test_bastard_html_uses_team_name_address(self):
        from services.aqua_keys import resolve_html_buyer_profile

        session = AsyncMock()
        user = SimpleNamespace(id=1)
        cfg = SimpleNamespace(team_id="bastard", profile_id="")

        async def _field(_s, _u, _tid, field):
            return {"buyer_name": "Kiss Anna", "address": "Andrássy út 12, Budapest"}.get(field, "")

        with (
            patch(
                "services.api_teams.get_selected_team_config",
                new=AsyncMock(return_value=cfg),
            ),
            patch(
                "services.api_teams.get_team_field",
                new=_field,
            ),
        ):
            name, addr = await resolve_html_buyer_profile(session, user)
        self.assertEqual(name, "Kiss Anna")
        self.assertIn("Budapest", addr)

    async def test_rpc_html_uses_team_name_address(self):
        from services.aqua_keys import resolve_html_buyer_profile

        session = AsyncMock()
        user = SimpleNamespace(id=1)
        cfg = SimpleNamespace(team_id="rpc", profile_id="https://api.rpc.example")

        async def _field(_s, _u, _tid, field):
            return {"buyer_name": "Nagy Péter", "address": "Budapest, HU"}.get(field, "")

        with (
            patch(
                "services.api_teams.get_selected_team_config",
                new=AsyncMock(return_value=cfg),
            ),
            patch(
                "services.api_teams.get_team_field",
                new=_field,
            ),
        ):
            name, addr = await resolve_html_buyer_profile(session, user)
        self.assertEqual(name, "Nagy Péter")
        self.assertIn("Budapest", addr)

    async def test_gag_html_uses_gag_name_address(self):
        from services.aqua_keys import resolve_html_buyer_profile

        session = AsyncMock()
        user = SimpleNamespace(id=1)
        cfg = SimpleNamespace(team_id="gag", profile_id="")

        async def _field(_s, _u, team_id, field):
            self.assertEqual(team_id, "gag")
            return {
                "buyer_name": "Anna Gremlis",
                "address": "Panoramastrasse 11, 6052 Hergiswil",
            }.get(field, "")

        with (
            patch(
                "services.api_teams.get_selected_team_config",
                new=AsyncMock(return_value=cfg),
            ),
            patch(
                "services.api_teams.get_team_field",
                new=_field,
            ),
        ):
            name, addr = await resolve_html_buyer_profile(session, user)
        self.assertEqual(name, "Anna Gremlis")
        self.assertIn("Hergiswil", addr)


class HtmlDialogPinTests(unittest.IsolatedAsyncioTestCase):
    async def test_resolve_link_prefers_conversation_over_stale_mail(self):
        from services.html_reply import resolve_aqua_link_for_reply

        session = AsyncMock()
        conv = SimpleNamespace(
            generated_link="https://new.example/95",
            last_generated_price="95.00 EUR",
        )
        exec_r = MagicMock()
        exec_r.scalars.return_value.first.return_value = conv
        session.execute = AsyncMock(return_value=exec_r)
        link = await resolve_aqua_link_for_reply(
            session,
            1,
            account_email="inbox@gmail.com",
            seller_email="seller@gmail.com",
            mail_generated_link="https://old.example/0",
        )
        self.assertEqual(link, "https://new.example/95")

    async def test_html_ctx_uses_pinned_price_not_listing_zero(self):
        session = AsyncMock()
        session.get = AsyncMock(return_value=SimpleNamespace(id=1))
        offer = SimpleNamespace(
            id=10,
            title="TUNTURI",
            price="0 €",
            photo="",
            raw_json='{"item_title":"TUNTURI","item_price":"0 €"}',
            user_id=1,
        )
        mail = SimpleNamespace(
            resolved_offer_id=10,
            product_title="TUNTURI",
            offer_price="0 €",
            photo_url="",
            account_email="inbox@gmail.com",
        )
        conv = SimpleNamespace(
            generated_link="https://new.example/95",
            last_generated_price="95.00 EUR",
        )

        async def _exec(_stmt):
            sql = str(_stmt)
            out = MagicMock()
            if "conversation_links" in sql.lower() or "ConversationLink" in sql:
                out.scalars.return_value.first.return_value = conv
            else:
                out.scalars.return_value.first.return_value = offer
            return out

        session.execute = AsyncMock(side_effect=_exec)
        with (
            patch(
                "services.aqua_keys.resolve_html_buyer_profile",
                new=AsyncMock(return_value=("Maria", "Amsterdam")),
            ),
            patch(
                "services.html_reply.get_spoof_display_name",
                new=AsyncMock(return_value=""),
            ),
            patch(
                "services.enabled_countries.get_active_country",
                new=AsyncMock(return_value="nl"),
            ),
        ):
            ctx = await build_offer_html_ctx(
                session, 1, "seller@gmail.com", link="", mail=mail
            )
        self.assertIn("95", ctx["PRICE"])
        self.assertNotIn("EUR 0", ctx["PRICE"])

    async def test_html_ctx_pin_overwrites_stale_zero_link(self):
        session = AsyncMock()
        session.get = AsyncMock(return_value=SimpleNamespace(id=1))
        mail = SimpleNamespace(
            resolved_offer_id=None,
            product_title="Schemerlamp",
            offer_price="0 €",
            photo_url="",
            account_email="sara.tonefeda38@gmail.com",
        )
        conv = SimpleNamespace(
            generated_link="https://marktplaats.id/56",
            last_generated_price="56.00 EUR",
            pinned_offer_id=None,
        )

        async def _exec(_stmt):
            out = MagicMock()
            out.scalars.return_value.first.return_value = conv
            return out

        session.execute = AsyncMock(side_effect=_exec)
        with (
            patch(
                "services.aqua_keys.resolve_html_buyer_profile",
                new=AsyncMock(return_value=("Maria", "Amsterdam")),
            ),
            patch(
                "services.html_reply.get_spoof_display_name",
                new=AsyncMock(return_value=""),
            ),
            patch(
                "services.enabled_countries.get_active_country",
                new=AsyncMock(return_value="nl"),
            ),
        ):
            ctx = await build_offer_html_ctx(
                session,
                1,
                "anjalaan@gmail.com",
                link="https://old.example/0",
                mail=mail,
                account_email="inbox@gmail.com",
            )
        self.assertIn("56", ctx["PRICE"])
        self.assertEqual(ctx["LINK"], "https://marktplaats.id/56")

    async def test_html_ctx_prefers_offer_aqua_pin_over_first_link(self):
        session = AsyncMock()
        session.get = AsyncMock(return_value=SimpleNamespace(id=1))
        offer = SimpleNamespace(
            id=10,
            title="Cortina",
            price="30.00 EUR",
            photo="",
            raw_json=(
                '{"item_title":"Cortina","item_price":"0 €",'
                '"aqua_generated_link":"https://marktplaats.id/new30",'
                '"aqua_generated_price":"30.00 EUR"}'
            ),
            user_id=1,
        )
        mail = SimpleNamespace(
            resolved_offer_id=10,
            product_title="Cortina",
            offer_price="0 €",
            photo_url="",
            account_email="inbox@gmail.com",
            generated_link="https://marktplaats.id/first0",
        )
        conv = SimpleNamespace(
            generated_link="https://marktplaats.id/first0",
            last_generated_price="0 €",
            pinned_offer_id=10,
        )

        async def _exec(_stmt):
            out = MagicMock()
            sql = str(_stmt)
            if "conversation_links" in sql.lower() or "ConversationLink" in sql:
                out.scalars.return_value.first.return_value = conv
            else:
                out.scalars.return_value.first.return_value = offer
            return out

        session.execute = AsyncMock(side_effect=_exec)
        with (
            patch(
                "services.aqua_keys.resolve_html_buyer_profile",
                new=AsyncMock(return_value=("Maria", "Amsterdam")),
            ),
            patch(
                "services.html_reply.get_spoof_display_name",
                new=AsyncMock(return_value=""),
            ),
            patch(
                "services.enabled_countries.get_active_country",
                new=AsyncMock(return_value="nl"),
            ),
        ):
            ctx = await build_offer_html_ctx(
                session,
                1,
                "seller@gmail.com",
                link="https://marktplaats.id/first0",
                mail=mail,
            )
        self.assertEqual(ctx["LINK"], "https://marktplaats.id/new30")
        self.assertIn("30", ctx["PRICE"])


class DialogEmailCanonTests(unittest.TestCase):
    def test_gmail_dots_share_match_keys(self):
        from services.email_address import dialog_email_match_keys, canonicalize_dialog_email

        dotted = "sara.tonefeda38@gmail.com"
        compact = "saratonefeda38@gmail.com"
        self.assertEqual(canonicalize_dialog_email(dotted), compact)
        keys = dialog_email_match_keys(dotted)
        self.assertIn(compact, keys)
        self.assertIn(dotted, keys)


if __name__ == "__main__":
    unittest.main()
