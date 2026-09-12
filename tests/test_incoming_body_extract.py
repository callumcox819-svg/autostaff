import unittest
from email.message import EmailMessage

from services.email_threading import format_gmail_style_reply_body, thread_contact_aliases
from services.incoming_mail_worker import _extract_text_from_msg


class IncomingBodyExtractTests(unittest.TestCase):
    def test_multipart_alternative_does_not_duplicate_plain_and_html(self):
        msg = EmailMessage()
        msg["Subject"] = "Re: fiets"
        plain = (
            "Yes!\n\n"
            "Op za 12 sep 2026 om 13:20 schreef Maria Zeglier :\n"
            "> Hallo, ik heb interesse\n"
            "> Alvast bedankt\n"
        )
        html = (
            "<p>Yes!</p>"
            "<p>Op za 12 sep 2026 om 13:20 schreef Maria Zeglier :</p>"
            "<p>Hallo, ik heb interesse<br>Alvast bedankt</p>"
        )
        msg.set_content(plain)
        msg.add_alternative(html, subtype="html")
        body = _extract_text_from_msg(msg)
        self.assertEqual(body.count("Yes!"), 1)
        self.assertIn("Hallo, ik heb interesse", body)
        self.assertNotIn("<p>", body)

    def test_gmail_quote_stops_at_dutch_schreef(self):
        out = format_gmail_style_reply_body(
            "Prima",
            parent_from_name="Caroline",
            parent_from_email="c@x.com",
            parent_date_str="Sat, 12 Sep 2026",
            parent_body=(
                "Yes!\n\n"
                "Op za 12 sep 2026 om 13:20 schreef Maria Zeglier :\n"
                "> Hallo mailing"
            ),
        )
        self.assertTrue(out.startswith("Prima\n\n"))
        self.assertIn("> Yes!", out)
        self.assertNotIn("Hallo mailing", out)

    def test_thread_aliases_keeps_mailed_and_reply_from(self):
        got = thread_contact_aliases("kaatje@x.com", "caroline@gmail.com")
        self.assertEqual(got, ["kaatje@x.com", "caroline@gmail.com"])


if __name__ == "__main__":
    unittest.main()
