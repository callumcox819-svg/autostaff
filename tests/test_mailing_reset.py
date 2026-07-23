import unittest

from services.mailing_reset import parse_mailing_reset_since


class TestMailingReset(unittest.TestCase):
    def test_parse_reset_since(self):
        dt = parse_mailing_reset_since("2026-06-09 12:30:45")
        self.assertIsNotNone(dt)
        self.assertEqual(dt.year, 2026)
        self.assertEqual(dt.month, 6)
        self.assertEqual(dt.day, 9)

    def test_parse_empty(self):
        self.assertIsNone(parse_mailing_reset_since(None))
        self.assertIsNone(parse_mailing_reset_since("  "))


if __name__ == "__main__":
    unittest.main()
