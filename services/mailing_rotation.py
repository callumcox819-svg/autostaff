"""Ротация Gmail-ящиков и пар target↔account для burst без перегрева одного ящика."""

from __future__ import annotations

import random
from typing import List, Sequence, Tuple

from sqlalchemy import func, select

from models import EmailAccount, MailingSendLog, OfferEmail


async def last_sent_ts_by_account(session, user_id: int) -> dict[str, float]:
    """email.lower() → unix time последней успешной рассылки (0 если не было)."""
    rows = (
        await session.execute(
            select(
                MailingSendLog.from_account_email,
                func.max(MailingSendLog.sent_at),
            )
            .where(MailingSendLog.user_id == int(user_id))
            .where(MailingSendLog.from_account_email.is_not(None))
            .group_by(MailingSendLog.from_account_email)
        )
    ).all()
    out: dict[str, float] = {}
    for em, dt in rows:
        key = (em or "").strip().lower()
        if not key:
            continue
        try:
            out[key] = float(dt.timestamp()) if dt else 0.0
        except Exception:
            out[key] = 0.0
    return out


async def sent_count_last_hour_by_account(session, user_id: int) -> dict[str, int]:
    """email.lower() → число успешных отправок за последний час."""
    from datetime import datetime, timedelta

    since = datetime.utcnow() - timedelta(hours=1)
    rows = (
        await session.execute(
            select(
                MailingSendLog.from_account_email,
                func.count(MailingSendLog.id),
            )
            .where(MailingSendLog.user_id == int(user_id))
            .where(MailingSendLog.from_account_email.is_not(None))
            .where(MailingSendLog.sent_at >= since)
            .group_by(MailingSendLog.from_account_email)
        )
    ).all()
    out: dict[str, int] = {}
    for em, cnt in rows:
        key = (em or "").strip().lower()
        if not key:
            continue
        out[key] = int(cnt or 0)
    return out


def order_accounts_for_burst(
    accounts: Sequence[EmailAccount],
    *,
    last_sent: dict[str, float] | None = None,
) -> List[EmailAccount]:
    """
    Сначала ящики, которые давно не слали (или никогда) — равномерная нагрузка + inbox.
    """
    rank = last_sent or {}

    def _key(acc: EmailAccount) -> float:
        em = (acc.email or "").strip().lower()
        base = rank.get(em, 0.0)
        return base + random.uniform(0, 0.02)

    ordered = sorted(list(accounts), key=_key)
    # Лёгкий shuffle соседних групп — не один и тот же порядок каждый /send
    if len(ordered) > 2:
        chunk = max(2, min(4, len(ordered) // 3 or 2))
        for i in range(0, len(ordered), chunk):
            part = ordered[i : i + chunk]
            random.shuffle(part)
            ordered[i : i + chunk] = part
    return ordered


def pair_targets_with_accounts(
    targets: Sequence[OfferEmail],
    accounts: Sequence[EmailAccount],
) -> List[Tuple[OfferEmail, EmailAccount]]:
    acc_list = list(accounts)
    if not acc_list:
        return []
    n_acc = len(acc_list)
    # Смещение старта — не всегда один и тот же ящик на первый адрес очереди
    offset = random.randrange(n_acc) if n_acc else 0
    return [(tgt, acc_list[(offset + i) % n_acc]) for i, tgt in enumerate(targets)]
