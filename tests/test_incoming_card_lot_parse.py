import unittest

from handlers.incoming_mail import _offer_id_from_incoming_card_message


class _Msg:
    def __init__(self, *, html_text: str | None = None, text: str | None = None):
        self.html_text = html_text
        self.text = text


class IncomingCardLotParseTests(unittest.TestCase):
    def test_parses_lot_from_html_card(self):
        html = (
            "<b>От:</b> zaur@bluewin.ch\n"
            "<b>Лот:</b> <code>89574</code>\n"
            "<b>Товар:</b> Mobiles Kühlgerät"
        )
        self.assertEqual(_offer_id_from_incoming_card_message(_Msg(html_text=html)), 89574)

    def test_no_lot_returns_none(self):
        self.assertIsNone(
            _offer_id_from_incoming_card_message(_Msg(html_text="<b>От:</b> a@b.ch"))
        )


if __name__ == "__main__":
    unittest.main()
