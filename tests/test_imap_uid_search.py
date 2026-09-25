import unittest

from services.incoming_mail_worker import (
    _inbox_uid_batch,
    _imap_status_uidnext,
    _parse_imap_uid_list,
)


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

    def test_inbox_batch_does_not_skip_older_uids(self):
        take, cursor = _inbox_uid_batch(100, list(range(101, 121)), limit=10)
        self.assertEqual(take, list(range(101, 111)))
        self.assertEqual(cursor, 110)
        take2, cursor2 = _inbox_uid_batch(110, list(range(101, 121)), limit=10)
        self.assertEqual(take2, list(range(111, 121)))
        self.assertEqual(cursor2, 120)

    def test_inbox_batch_empty_keeps_cursor(self):
        take, cursor = _inbox_uid_batch(50, [], limit=10)
        self.assertEqual(take, [])
        self.assertEqual(cursor, 50)


if __name__ == "__main__":
    unittest.main()
