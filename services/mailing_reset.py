"""Сброс очереди рассылки (/reset) — как poputka88."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import delete, select

from models import Offer, OfferEmail, UserSetting
from services.user_settings import delete_user_setting, get_user_setting

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


async def _upsert_setting_flush(session, user_id: int, key: str, value: str) -> None:
    """Пишем setting без вложенного commit (иначе /reset падает на большой очереди)."""
    row = (
        await session.execute(
            select(UserSetting).where(
                UserSetting.user_id == int(user_id),
                UserSetting.key == key,
            )
        )
    ).scalar_one_or_none()
    if row:
        row.value = value
        return
    session.add(
        UserSetting(
            user_id=int(user_id),
            key=key,
            value=value,
            html_nick="",
            html_signature="",
            sender_name="",
        )
    )


async def mark_mailing_queue_reset(session, user_id: int, *, skip_emails: set[str]) -> None:
    """После /reset в очередь не возвращаются email, убранные сбросом."""
    await _upsert_setting_flush(session, user_id, MAILING_RESET_SINCE_KEY, _utc_now_str())
    payload = json.dumps(sorted(skip_emails), ensure_ascii=False)
    # Не раздуваем user_settings до десятков МБ — since уже режет старую очередь.
    if len(payload) > 900_000:
        payload = json.dumps(sorted(skip_emails)[:12000], ensure_ascii=False)
    await _upsert_setting_flush(session, user_id, MAILING_RESET_SKIP_EMAILS_KEY, payload)


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
        try:
            from handlers.stopsend import stop_sending_for_user

            stop_sending_for_user(int(tg_user_id))
        except Exception:
            pass

    uid = int(user_id)
    offer_subq = select(Offer.id).where(Offer.user_id == uid)

    skip_emails: set[str] = set()
    for em in (
        await session.execute(
            select(OfferEmail.email)
            .join(Offer, Offer.id == OfferEmail.offer_id)
            .where(Offer.user_id == uid)
        )
    ).scalars().all():
        e = (str(em or "")).strip().lower()
        if e:
            skip_emails.add(e)

    res = await session.execute(
        delete(OfferEmail).where(OfferEmail.offer_id.in_(offer_subq))
    )
    removed = int(res.rowcount or 0)
    await session.flush()

    await mark_mailing_queue_reset(session, uid, skip_emails=skip_emails)
    return {"removed": removed, "skip_emails": len(skip_emails)}
