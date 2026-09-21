import unittest

from services.incoming_mail_worker import _imap_status_uidnext, _parse_imap_uid_list


class ImapUidHelpersTests(unittest.TestCase):
    def test_parse_uid_list(self):
        self.assertEqual(_parse_imap_uid_list([b"101 102 103"]), [101, 102, 103])
        self.assertEqual(_parse_imap_uid_list([None]), [])
        self.assertEqual(_parse_imap_uid_list(None), [])

    def test_uidnext_status(self):
        class Fake:
            def status(self, mailbox, items):
                return "OK", [b"INBOX (UIDNEXT 44521)"]

        self.assertEqual(_imap_status_uidnext(Fake()), 44521)


if __name__ == "__main__":
    unittest.main()
