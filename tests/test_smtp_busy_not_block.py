import unittest


class SmtpBusyNotBlockTests(unittest.TestCase):
    def test_421_server_busy_is_not_account_block(self):
        from services.smtp_block_control import (
            is_smtp_account_block_error,
            is_temporary_smtp_busy,
        )

        err = (
            "ACCOUNT_RATE_LIMIT:421:b'4.4.5 Server busy, try again later. "
            "(mx.google.com)\\n4.4.5 For more information, go to\\n4.4.5 "
            "https://support.google.com/a/answer/3221692 - gsmtp'"
        )
        self.assertTrue(is_temporary_smtp_busy(err))
        self.assertFalse(is_smtp_account_block_error(err))

    def test_daily_limit_still_blocks(self):
        from services.smtp_block_control import is_smtp_account_block_error

        err = "ACCOUNT_RATE_LIMIT:550:5.4.5 Daily user sending limit exceeded"
        self.assertTrue(is_smtp_account_block_error(err))

    def test_invalid_credentials_is_dead_not_smtp_pause(self):
        from services.smtp_account_check import is_account_no_access_error
        from services.smtp_block_control import is_smtp_account_block_error

        err = (
            "ACCOUNT_INVALID_CREDENTIALS:534:5.7.9 Please log in with your web browser "
            "and then try again. For more 5.7.9 information, go to 5.7.9 "
            "https://support.google.com/mail/?p=WebLoginRequired"
        )
        self.assertTrue(is_account_no_access_error(err))
        self.assertFalse(is_smtp_account_block_error(err))


class GmailSenderBlockBounceTests(unittest.TestCase):
    def test_indonesian_pesan_diblokir_is_smtp_block(self):
        from services.incoming_mail_worker import _is_smtp_block_bounce
        from services.smtp_block_control import is_gmail_sender_block_text

        body = (
            "** Pesan diblokir **\n"
            "Pesan Anda untuk dankbaar@gmail.com telah diblokir. "
            "https://support.google.com/mail/answer/69585\n"
            "Message rejected."
        )
        self.assertTrue(is_gmail_sender_block_text(body))
        self.assertTrue(
            _is_smtp_block_bounce(
                "mailer-daemon@googlemail.com",
                "Delivery Status Notification (Failure)",
                body,
            )
        )

    def test_english_message_blocked_still_matches(self):
        from services.incoming_mail_worker import _is_smtp_block_bounce

        self.assertTrue(
            _is_smtp_block_bounce(
                "mailer-daemon@googlemail.com",
                "Delivery Status Notification (Failure)",
                "Message blocked. Your message to x@gmail.com has been blocked.",
            )
        )

    def test_recipient_inbox_full_is_not_sender_block(self):
        from services.bounce_recipient import is_recipient_delivery_failure_bounce
        from services.incoming_mail_worker import _is_smtp_block_bounce

        body = (
            "** Kotak masuk penerima penuh **\n"
            "Pesan Anda tidak dapat dikirim ke klimtuin@gmail.com. "
            "Kotak masuknya penuh.\n"
            "https://support.google.com/mail/?p=OverQuotaPerm\n"
            "552 5.2.2 The recipient's inbox is out of storage space"
        )
        self.assertFalse(
            _is_smtp_block_bounce(
                "mailer-daemon@googlemail.com",
                "Delivery Status Notification (Failure)",
                body,
            )
        )
        self.assertTrue(is_recipient_delivery_failure_bounce("Delivery Status Notification (Failure)", body))


if __name__ == "__main__":
    unittest.main()
