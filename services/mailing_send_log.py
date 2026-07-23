"""Журнал успешных отправок — как recipients.lead_id в poputka88."""

from __future__ import annotations

from sqlalchemy import func, or_, select

from models import MailingSendLog, Offer
from services.offer_matching import canon_seller_email, product_title_from_subject, subject_title_agrees
from services.offer_storage import offer_effective_link, offer_effective_title


def _canon_recipient(email: str) -> str:
    return canon_seller_email((email or "").strip())


async def record_mailing_send(
    session,
    *,
    user_id: int,
    offer_id: int,
    recipient_email: str,
    mail_subject: str = "",
    from_account_email: str = "",
    offer_email_id: int | None = None,
) -> None:
    """Записать: этому email ушло письмо по конкретному offer_id."""
    rcpt = _canon_recipient(recipient_email)
    if not rcpt or not int(offer_id or 0):
        return
    row = MailingSendLog(
        user_id=int(user_id),
        offer_id=int(offer_id),
        recipient_email=rcpt,
        mail_subject=(mail_subject or "").strip()[:500] or None,
        from_account_email=(from_account_email or "").strip().lower()[:255] or None,
        offer_email_id=int(offer_email_id) if offer_email_id else None,
    )
    session.add(row)


async def _mailing_log_rows_for_recipient(
    session,
    user_id: int,
    contact_email: str,
    *,
    limit: int = 400,
) -> list[tuple[MailingSendLog, Offer]]:
    """Строки журнала рассылки на этот email (канонизация gmail/+alias)."""
    email = _canon_recipient(contact_email)
    if not email:
        return []

    raw = (contact_email or "").strip().lower()
    conds = [func.lower(MailingSendLog.recipient_email) == email]
    if raw and raw != email:
        conds.append(func.lower(MailingSendLog.recipient_email) == raw)

    rows = (
        await session.execute(
            select(MailingSendLog, Offer)
            .join(Offer, Offer.id == MailingSendLog.offer_id)
            .where(MailingSendLog.user_id == int(user_id))
            .where(or_(*conds))
            .order_by(MailingSendLog.sent_at.desc(), MailingSendLog.id.desc())
            .limit(int(limit))
        )
    ).all()

    if rows:
        return list(rows)

    # Старые записи могли сохраниться без канонизации — добираем из недавних отправок.
    broad = (
        await session.execute(
            select(MailingSendLog, Offer)
            .join(Offer, Offer.id == MailingSendLog.offer_id)
            .where(MailingSendLog.user_id == int(user_id))
            .order_by(MailingSendLog.sent_at.desc(), MailingSendLog.id.desc())
            .limit(int(limit))
        )
    ).all()
    out: list[tuple[MailingSendLog, Offer]] = []
    for log, off in broad:
        if _canon_recipient(log.recipient_email or "") == email:
            out.append((log, off))
    return out


async def list_offers_from_mailing_log(
    session,
    user_id: int,
    contact_email: str,
    *,
    limit: int = 80,
) -> list[Offer]:
    """Все лоты, на которые рассылали этому продавцу (после purge OfferEmail)."""
    rows = await _mailing_log_rows_for_recipient(session, user_id, contact_email, limit=400)
    seen: set[int] = set()
    out: list[Offer] = []
    for _log, off in rows:
        oid = int(off.id)
        if oid in seen:
            continue
        seen.add(oid)
        out.append(off)
        if len(out) >= int(limit):
            break
    return out


async def offer_was_mailed_to(
    session,
    user_id: int,
    offer_id: int,
    contact_email: str,
) -> bool:
    email = _canon_recipient(contact_email)
    if not email or not int(offer_id or 0):
        return False
    rows = (
        await session.execute(
            select(MailingSendLog)
            .where(MailingSendLog.user_id == int(user_id))
            .where(MailingSendLog.offer_id == int(offer_id))
            .order_by(MailingSendLog.sent_at.desc(), MailingSendLog.id.desc())
            .limit(40)
        )
    ).scalars().all()
    return any(_canon_recipient(r.recipient_email or "") == email for r in rows)


async def find_offer_from_mailing_log(
    session,
    user_id: int,
    contact_email: str,
    subject: str = "",
) -> tuple[Offer | None, str]:
    """
    Лот из последней рассылки на этот email (poputka: get_lead_for_mailing_recipient).
    Если несколько — уточняем по теме Re:.
    """
    rows = await _mailing_log_rows_for_recipient(session, user_id, contact_email, limit=400)

    if not rows:
        return None, ""

    subj_needle = product_title_from_subject(subject)
    if subj_needle:
        for _log, off in rows:
            if subject_title_agrees(subject, off):
                link = (offer_effective_link(off) or "").strip()
                if link:
                    return off, "mailing_subject"
            sent_subj = (_log.mail_subject or "").strip()
            if sent_subj and subj_needle.lower() in sent_subj.lower():
                link = (offer_effective_link(off) or "").strip()
                if link:
                    return off, "mailing_sent_subject"
            ot = (offer_effective_title(off) or "").strip()
            if ot and subj_needle.lower() in ot.lower():
                link = (offer_effective_link(off) or "").strip()
                if link:
                    return off, "mailing_title"

    _log, off = rows[0]
    link = (offer_effective_link(off) or "").strip()
    if link:
        return off, "mailing_latest"
    return None, ""
