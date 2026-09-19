import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from services.smtp_block_control import (
    apply_smtp_blocked_fields,
    clear_smtp_blocked_fields,
    new_smtp_blocked_until,
    restore_due_smtp_blocked_accounts,
    smtp_block_cooldown_hours_range,
)


class SmtpBlockCooldownTests(unittest.TestCase):
    def test_cooldown_range_defaults(self):
        lo, hi = smtp_block_cooldown_hours_range()
        self.assertAlmostEqual(lo, 5.0)
        self.assertAlmostEqual(hi, 6.0)

    def test_new_until_within_range(self):
        now = datetime(2026, 1, 1, 12, 0, 0)
        for _ in range(20):
            until = new_smtp_blocked_until(now=now)
            delta_h = (until - now).total_seconds() / 3600.0
            self.assertGreaterEqual(delta_h, 5.0 - 1e-9)
            self.assertLessEqual(delta_h, 6.0 + 1e-9)

    def test_apply_does_not_reset_timer_if_already_blocked(self):
        fixed = datetime(2026, 1, 1, 18, 0, 0)
        acc = SimpleNamespace(
            status="smtp_blocked",
            last_error="old",
            smtp_blocked_until=fixed,
        )
        newly = apply_smtp_blocked_fields(acc, "message blocked again")
        self.assertFalse(newly)
        self.assertEqual(acc.smtp_blocked_until, fixed)
        self.assertEqual(acc.last_error, "message blocked again")

    def test_clear_fields(self):
        acc = SimpleNamespace(
            status="smtp_blocked",
            last_error="x",
            smtp_blocked_until=datetime.utcnow(),
        )
        clear_smtp_blocked_fields(acc)
        self.assertEqual(acc.status, "active")
        self.assertIsNone(acc.last_error)
        self.assertIsNone(acc.smtp_blocked_until)


class SmtpBlockRestoreTests(unittest.IsolatedAsyncioTestCase):
    async def test_restore_due_accounts(self):
        past = datetime.utcnow() - timedelta(hours=1)
        future = datetime.utcnow() + timedelta(hours=3)
        due = SimpleNamespace(
            id=1,
            status="smtp_blocked",
            last_error="blocked",
            smtp_blocked_until=past,
            updated_at=past,
        )
        not_due = SimpleNamespace(
            id=2,
            status="smtp_blocked",
            last_error="blocked",
            smtp_blocked_until=future,
            updated_at=future,
        )
        session = AsyncMock()
        exec_result = MagicMock()
        exec_result.scalars.return_value.all.return_value = [due, not_due]
        session.execute = AsyncMock(return_value=exec_result)
        session.commit = AsyncMock()
        session.rollback = AsyncMock()

        n = await restore_due_smtp_blocked_accounts(session)
        self.assertEqual(n, 1)
        self.assertEqual(due.status, "active")
        self.assertIsNone(due.smtp_blocked_until)
        self.assertEqual(not_due.status, "smtp_blocked")
        session.commit.assert_awaited()


if __name__ == "__main__":
    unittest.main()
