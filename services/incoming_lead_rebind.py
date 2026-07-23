"""Перепривязка старых incoming_mails к лотам (после purge OfferEmail / до mailing_send_log)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import IncomingMail
from services.incoming_lead_resolve import resolve_offer_for_incoming_lead
from services.incoming_mail_worker import (
    _is_automated_system_sender,
    _is_google_system_mail,
    _is_mailer_daemon_notice,
    _is_recipient_delivery_failure_bounce,
    _is_smtp_block_bounce,
)
from services.incoming_mail_stats import _is_auto_reply, _is_platform_sender


def _should_rebind_row(row: IncomingMail) -> bool:
    fe = row.from_email or ""
    fn = row.from_name or ""
    subj = row.subject or ""
    body = row.body or ""

    if _is_smtp_block_bounce(fe, subj, body):
        return False
    if _is_mailer_daemon_notice(fe, subj):
        return False
    if _is_google_system_mail(fe, fn, subj):
        return False
    if _is_automated_system_sender(fe, fn, subj):
        return False
    if _is_auto_reply(subj, body):
        return False
    if _is_platform_sender(fe):
        return False
    return True


async def rebind_incoming_mail_row(session: AsyncSession, row: IncomingMail) -> str:
    """
    Перезапуск resolve для одной строки.
    Returns: updated | unchanged | skipped
    """
    if not _should_rebind_row(row):
        return "skipped"

    prev_offer = row.resolved_offer_id
    prev_bound = bool(getattr(row, "mailing_bound", False))
    prev_title = (row.product_title or "").strip()

    offer, listing_url, _how, snap = await resolve_offer_for_incoming_lead(
        session,
        user_id=int(row.user_id),
        contact_email=(row.from_email or "").strip(),
        subject=(row.subject or "").strip(),
        from_name=(row.from_name or "").strip(),
        body_text=(row.body or "").strip(),
        resolved_offer_id=row.resolved_offer_id,
        mail_ad_url=(row.ad_url or "").strip() or None,
        inbox_email=(row.account_email or "").strip() or None,
        mailing_bound=prev_bound,
    )

    if not offer:
        return "unchanged"

    new_offer = int(offer.id)
    new_bound = bool(snap.get("mailing_bound"))
    row.resolved_offer_id = new_offer
    row.mailing_bound = new_bound
    if listing_url:
        row.ad_url = listing_url.strip()

    for key, max_len in (
        ("product_title", None),
        ("offer_price", 64),
        ("photo_url", None),
        ("service_label", 64),
    ):
        val = (snap.get(key) or "").strip()
        if not val:
            continue
        if max_len:
            val = val[:max_len]
        setattr(row, key, val)

    changed = (
        prev_offer != new_offer
        or prev_bound != new_bound
        or (snap.get("product_title") or "").strip() != prev_title
    )
    return "updated" if changed else "unchanged"


async def rebind_stale_incoming_mails(
    session: AsyncSession,
    db_user_id: int,
    *,
    limit: int = 500,
) -> dict[str, int]:
    """
    Перепривязка писем без mailing_bound или без resolved_offer_id.
    Вызывается из /imap_diag (разовый backfill на проде).
    """
    rows = (
        await session.execute(
            select(IncomingMail)
            .where(IncomingMail.user_id == int(db_user_id))
            .order_by(IncomingMail.id.desc())
            .limit(int(limit))
        )
    ).scalars().all()

    stats = {"scanned": 0, "updated": 0, "unchanged": 0, "skipped": 0}
    for row in rows:
        stats["scanned"] += 1
        outcome = await rebind_incoming_mail_row(session, row)
        stats[outcome] = int(stats.get(outcome, 0)) + 1

    if stats["updated"]:
        await session.commit()
    return stats
