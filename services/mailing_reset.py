"""Сброс очереди рассылки (/reset) — как poputka88."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import delete, select

from models import Offer, OfferEmail
from services.user_settings import delete_user_setting, get_user_setting, set_user_setting

MAILING_RESET_SINCE_KEY = "mailing_reset_since"
MAILING_RESET_SKIP_EMAILS_KEY = "mailing_reset_skip_emails"


def _utc_now_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def parse_mailing_reset_since(raw: str | None) -> datetime | None:
    s = (raw or "").strip()
    if not s:
        return None
    s = s.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s) if "T" in s else datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


async def get_mailing_reset_since(session, user_id: int) -> str | None:
    raw = await get_user_setting(session, user_id, MAILING_RESET_SINCE_KEY)
    return (raw or "").strip() or None


async def get_mailing_reset_skip_emails(session, user_id: int) -> set[str]:
    raw = await get_user_setting(session, user_id, MAILING_RESET_SKIP_EMAILS_KEY)
    if not raw:
        return set()
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return {str(e).strip().lower() for e in data if str(e).strip()}
    except Exception:
        pass
    return {e.strip().lower() for e in str(raw).split(",") if e.strip()}


async def mark_mailing_queue_reset(session, user_id: int, *, skip_emails: set[str]) -> None:
    """После /reset в очередь не возвращаются email, убранные сбросом."""
    await set_user_setting(session, user_id, MAILING_RESET_SINCE_KEY, _utc_now_str())
    await set_user_setting(
        session,
        user_id,
        MAILING_RESET_SKIP_EMAILS_KEY,
        json.dumps(sorted(skip_emails), ensure_ascii=False),
    )


async def clear_mailing_reset(session, user_id: int) -> None:
    await delete_user_setting(session, user_id, MAILING_RESET_SINCE_KEY)
    await delete_user_setting(session, user_id, MAILING_RESET_SKIP_EMAILS_KEY)


async def reset_user_mailing_queue(
    session,
    user_id: int,
    *,
    tg_user_id: int | None = None,
) -> dict[str, int]:
    """Убрать все OfferEmail (очередь); Offer в БД не трогаем."""
    if tg_user_id is not None:
        from handlers.stopsend import stop_sending_for_user

        stop_sending_for_user(int(tg_user_id))

    offer_ids = [
        int(x)
        for x in (
            await session.execute(select(Offer.id).where(Offer.user_id == int(user_id)))
        ).scalars().all()
    ]

    skip_emails: set[str] = set()
    removed = 0
    if offer_ids:
        for em in (
            await session.execute(
                select(OfferEmail.email).where(OfferEmail.offer_id.in_(offer_ids))
            )
        ).scalars().all():
            e = (str(em or "")).strip().lower()
            if e:
                skip_emails.add(e)

        res = await session.execute(
            delete(OfferEmail).where(OfferEmail.offer_id.in_(offer_ids))
        )
        removed = int(res.rowcount or 0)

    await mark_mailing_queue_reset(session, user_id, skip_emails=skip_emails)
    return {"removed": removed, "skip_emails": len(skip_emails)}
