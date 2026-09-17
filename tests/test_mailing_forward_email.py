import unittest

from services.mailing_send_log import seller_emails_equivalent


class MailingForwardEmailTests(unittest.TestCase):
    def test_yahoo_de_com_same_local(self):
        self.assertTrue(
            seller_emails_equivalent("mike_maeder@yahoo.com", "mike_maeder@yahoo.de")
        )

    def test_different_local_false(self):
        self.assertFalse(
            seller_emails_equivalent("a@yahoo.com", "b@yahoo.de")
        )

    def test_gmail_dots_equivalent(self):
        self.assertTrue(
            seller_emails_equivalent(
                "michaela.lipburger@gmail.com",
                "michaelalipburger@gmail.com",
            )
        )


if __name__ == "__main__":
    unittest.main()
