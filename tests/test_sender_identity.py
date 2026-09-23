# -*- coding: utf-8 -*-
import unittest

from services.mailing_deliverability import finalize_inbox_mail
from services.sender_identity import merge_sender_name_history, strip_stale_sender_names


class SenderIdentityTests(unittest.TestCase):
    def test_history_keeps_old_drops_current(self):
        hist = merge_sender_name_history(
            ["Lisa Support"],
            old_name="Maria Johansen",
            new_name="Anna Genrightens",
        )
        self.assertEqual(hist[0], "Maria Johansen")
        self.assertIn("Lisa Support", hist)
        self.assertNotIn("Anna Genrightens", hist)

    def test_strip_previous_and_trailing_name(self):
        body = "Szia, elérhető még?\n\nÜdvözlettel\nMaria Johansen"
        out = strip_stale_sender_names(
            body,
            current_name="Anna Genrightens",
            previous_names=["Maria Johansen"],
        )
        self.assertNotIn("Maria Johansen", out)
        self.assertIn("Üdvözlettel", out)

    def test_preset_finalize_uses_only_latest_name(self):
        _, body = finalize_inbox_mail(
            "OFFER",
            "Guten Tag, ist der Artikel noch verfügbar?\n\nFreundliche Grüße\nOld Sender",
            country="ch",
            sender_name="Anna Genrightens",
            previous_sender_names=["Old Sender"],
            vary_body=False,
        )
        self.assertIn("Anna Genrightens", body)
        self.assertNotIn("Old Sender", body)
        self.assertEqual(body.count("Anna Genrightens"), 1)


if __name__ == "__main__":
    unittest.main()
