import unittest

from services.incoming_mail_worker import (
    _is_apple_system_mail,
    _is_automated_system_sender,
    _is_noreply_automated_sender,
    _is_platform_system_mail,
)


class TestNoreplyFilter(unittest.TestCase):
    def test_blocks_instagram_noreply(self):
        self.assertTrue(_is_noreply_automated_sender("no-reply@mail.instagram.com"))

    def test_blocks_common_noreply(self):
        for addr in (
            "noreply@google.com",
            "no_reply@shop.example",
            "donotreply@service.io",
            "no-reply+tag@domain.com",
        ):
            self.assertTrue(_is_noreply_automated_sender(addr), addr)

    def test_allows_seller_emails(self):
        for addr in (
            "kurt.seller@gmail.com",
            "info@2dehands-verkoper.be",
            "anna.zehringer@example.com",
            "harriettekukzr073@gmail.com",
        ):
            self.assertFalse(_is_noreply_automated_sender(addr), addr)

    def test_allows_mailer_daemon(self):
        self.assertFalse(_is_noreply_automated_sender("mailer-daemon@gmail.com"))

    def test_blocks_apple_id(self):
        self.assertTrue(_is_apple_system_mail("appleid@id.apple.com", "Apple"))
        self.assertTrue(
            _is_automated_system_sender("appleid@id.apple.com", "Apple", "Verify your Apple Account")
        )

    def test_allows_icloud_seller(self):
        self.assertFalse(_is_apple_system_mail("seller.name@icloud.com", "Jan"))

    def test_blocks_wallapop(self):
        self.assertTrue(_is_platform_system_mail("info@wallapop.com", "Wallapop"))
        self.assertTrue(
            _is_automated_system_sender(
                "info@wallapop.com",
                "Wallapop",
                "Código de verificación del email",
            )
        )

    def test_allows_seller_not_platform(self):
        self.assertFalse(_is_platform_system_mail("jan.verkoper@gmail.com", "Jan"))

    def test_blocks_facebookmail_not_whole_facebook_com(self):
        self.assertTrue(_is_platform_system_mail("noreply@facebookmail.com", "Facebook"))
        self.assertFalse(_is_platform_system_mail("someone@facebook.com", "John"))

    def test_blocks_amazon_account_update(self):
        self.assertTrue(
            _is_automated_system_sender(
                "account-update@amazon.co.jp",
                "Amazon.co.jp",
                "新しいAmazonアカウントの確認",
            )
        )
        self.assertTrue(_is_platform_system_mail("no-reply@amazon.com", "Amazon"))

    def test_blocks_snapchat_verification(self):
        self.assertTrue(
            _is_automated_system_sender(
                "verification@verify.snapchat.com",
                "Team Snapchat",
                "Confirm Your Email Address",
            )
        )

    def test_blocks_alibaba_notice(self):
        self.assertTrue(
            _is_automated_system_sender(
                "credit@notice.alibaba.com",
                "Alibaba",
                "Payment for your Trade Assurance order",
            )
        )


if __name__ == "__main__":
    unittest.main()
