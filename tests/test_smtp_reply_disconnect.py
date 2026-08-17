import unittest

from handlers.incoming_mail import _smtp_user_error
from services.sender import (
    normalize_send_error,
    should_retry_send_with_other_proxy,
    smtp_send_endpoints,
)


class SmtpReplyDisconnectTests(unittest.TestCase):
    def test_gmail_has_smtps_fallback(self):
        eps = smtp_send_endpoints("smtp.gmail.com", 587)
        self.assertEqual(eps[0], ("smtp.gmail.com", 587, False))
        self.assertEqual(eps[1], ("smtp.gmail.com", 465, True))

    def test_retry_on_server_disconnect(self):
        err = "SMTPServerDisconnected: Connection unexpectedly closed"
        self.assertTrue(should_retry_send_with_other_proxy(err))
        norm = normalize_send_error(err)
        self.assertTrue(norm.startswith("SMTP_TIMEOUT"))
        self.assertIn("disconnect", norm.lower())

    def test_user_error_hides_traceback(self):
        msg = _smtp_user_error("SMTPServerDisconnected: Connection unexpectedly closed")
        self.assertIn("прокси", msg.lower())
        self.assertNotIn("SMTPServerDisconnected", msg)

    def test_plain_timeout_keeps_kind(self):
        norm = normalize_send_error("timed out")
        self.assertTrue(norm.startswith("SMTP_TIMEOUT"))


if __name__ == "__main__":
    unittest.main()
