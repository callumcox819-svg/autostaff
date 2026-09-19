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


if __name__ == "__main__":
    unittest.main()
