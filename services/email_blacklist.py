"""Личный ЧС email на пользователя: валидированные + успешно отправленные.

Всё в БД. /reset очередь не чистит эти списки — повторно не валидируем и не шлём.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select

from models import SentEmail, ValidatedEmailBlacklist
from services.offer_matching import canon_seller_email


def _canon(email: str) -> str:
    return canon_seller_email((email or "").strip()) or (email or "").strip().lower()


async def load_validated_email_keys(session, user_id: int) -> set[str]:
    rows = (
        await session.execute(
            select(ValidatedEmailBlacklist.email).where(
                ValidatedEmailBlacklist.user_id == int(user_id)
            )
        )
    ).all()
    out: set[str] = set()
    for (em,) in rows:
        c = _canon(str(em or ""))
        if c:
            out.add(c)
    return out


async def load_sent_email_keys(session, user_id: int) -> set[str]:
    rows = (
        await session.execute(
            select(SentEmail.email).where(SentEmail.user_id == int(user_id))
        )
    ).all()
    out: set[str] = set()
    for (em,) in rows:
        c = _canon(str(em or ""))
        if c:
            out.add(c)
    return out


async def load_blocked_email_keys(session, user_id: int) -> set[str]:
    """Не ставить в очередь и не слать повторно: ЧС валид + ЧС отправленных."""
    keys = await load_validated_email_keys(session, int(user_id))
    keys |= await load_sent_email_keys(session, int(user_id))
    return keys


async def add_validated_email(
    session,
    user_id: int,
    email: str,
    *,
    offer_id: int | None = None,
) -> bool:
    """Записать email в ЧС валидированных (idempotent)."""
    canon = _canon(email)
    if not canon or "@" not in canon:
        return False
    uid = int(user_id)
    exists = (
        await session.execute(
            select(ValidatedEmailBlacklist.id)
            .where(ValidatedEmailBlacklist.user_id == uid)
            .where(func.lower(ValidatedEmailBlacklist.email) == canon)
            .limit(1)
        )
    ).scalar_one_or_none()
    if exists:
        return False
    session.add(
        ValidatedEmailBlacklist(
            user_id=uid,
            email=canon,
            offer_id=int(offer_id) if offer_id else None,
        )
    )
    return True


async def add_validated_emails_bulk(
    session,
    user_id: int,
    emails: set[str] | list[str],
    *,
    offer_id: int | None = None,
) -> int:
    added = 0
    for em in emails or []:
        if await add_validated_email(session, user_id, em, offer_id=offer_id):
            added += 1
    return added


async def mark_email_sent(session, user_id: int, email: str) -> bool:
    """ЧС отправленных: upsert SentEmail (личный, на user_id)."""
    canon = _canon(email)
    if not canon or "@" not in canon:
        return False
    uid = int(user_id)
    row = (
        await session.execute(
            select(SentEmail)
            .where(SentEmail.user_id == uid)
            .where(func.lower(SentEmail.email) == canon)
            .limit(1)
        )
    ).scalars().first()
    if row:
        row.sent_at = datetime.utcnow()
        row.sent_count = int(row.sent_count or 0) + 1
        if not (row.email or "").strip():
            row.email = canon
        return True
    session.add(
        SentEmail(
            user_id=uid,
            email=canon,
            sent_at=datetime.utcnow(),
            sent_count=1,
        )
    )
    return True


async def is_email_blocked_for_queue(session, user_id: int, email: str) -> bool:
    canon = _canon(email)
    if not canon:
        return False
    if (
        await session.execute(
            select(ValidatedEmailBlacklist.id)
            .where(ValidatedEmailBlacklist.user_id == int(user_id))
            .where(func.lower(ValidatedEmailBlacklist.email) == canon)
            .limit(1)
        )
    ).scalar_one_or_none():
        return True
    if (
        await session.execute(
            select(SentEmail.id)
            .where(SentEmail.user_id == int(user_id))
            .where(func.lower(SentEmail.email) == canon)
            .limit(1)
        )
    ).scalar_one_or_none():
        return True
    return False


async def is_email_already_sent(session, user_id: int, email: str) -> bool:
    canon = _canon(email)
    if not canon:
        return False
    row = (
        await session.execute(
            select(SentEmail.id)
            .where(SentEmail.user_id == int(user_id))
            .where(func.lower(SentEmail.email) == canon)
            .limit(1)
        )
    ).scalar_one_or_none()
    return row is not None
