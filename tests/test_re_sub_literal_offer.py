import unittest


class ReSubLiteralOfferTests(unittest.TestCase):
    def test_offer_title_with_octal_like_backslash_does_not_crash(self):
        from services.offer_text import apply_offer_to_text
        from services.placeholders import apply_placeholders
        from services.subject_offer import render_subject_with_offer

        # \512 — ровно ошибка из burst UI (re.sub replacement = octal)
        title = "012345678901234\\512 super deal"
        body = apply_offer_to_text("Hallo, OFFER noch da?", title)
        self.assertIn("\\512", body)
        self.assertIn("super deal", body)

        subj = render_subject_with_offer("Kurze Frage zu OFFER", title)
        self.assertIn("\\512", subj)

        out = apply_placeholders("Link: {{LINK}}", link="https://x.test/a\\512b")
        self.assertIn("\\512", out)

    def test_ctx_link_overrides_stale_link_arg(self):
        from services.placeholders import apply_placeholders

        out = apply_placeholders(
            "go {{LINK}}",
            link="https://old.example/0",
            ctx={"LINK": "https://new.example/56"},
        )
        self.assertEqual(out, "go https://new.example/56")


if __name__ == "__main__":
    unittest.main()
