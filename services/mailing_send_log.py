"""Журнал успешных отправок — как recipients.lead_id в poputka88."""

from __future__ import annotations

from sqlalchemy import func, or_, select

from models import MailingSendLog, Offer
from services.offer_matching import (
    canon_seller_email,
    incoming_subject_binds_offer,
    product_title_from_subject,
    subject_is_informative,
    subject_match_score,
    subject_title_agrees,
    _norm_subject,
)
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


async def offer_has_queued_email(
    session,
    user_id: int,
    offer_id: int,
    contact_email: str,
) -> bool:
    """OfferEmail ещё в очереди /send (до purge после отправки)."""
    from sqlalchemy import func, or_, select

    from models import Offer, OfferEmail

    email = _canon_recipient(contact_email)
    if not email or not int(offer_id or 0):
        return False
    raw = (contact_email or "").strip().lower()
    conds = [func.lower(OfferEmail.email) == email]
    if raw and raw != email:
        conds.append(func.lower(OfferEmail.email) == raw)
    row = (
        await session.execute(
            select(OfferEmail.id)
            .join(Offer, Offer.id == OfferEmail.offer_id)
            .where(Offer.user_id == int(user_id))
            .where(OfferEmail.offer_id == int(offer_id))
            .where(or_(*conds))
            .limit(1)
        )
    ).scalar_one_or_none()
    return row is not None


async def list_allowed_offers_for_incoming_contact(
    session,
    user_id: int,
    contact_email: str,
    *,
    limit: int = 80,
) -> list[Offer]:
    """Лоты, на которые реально валидировали/слали этому email (log + очередь OfferEmail)."""
    from services.offer_matching import list_offers_for_seller_email

    seen: set[int] = set()
    out: list[Offer] = []
    for off in await list_offers_from_mailing_log(
        session, int(user_id), contact_email, limit=limit
    ):
        oid = int(off.id)
        if oid in seen:
            continue
        seen.add(oid)
        out.append(off)
    for off in await list_offers_for_seller_email(
        session, user_id=int(user_id), from_email=contact_email
    ):
        oid = int(off.id)
        if oid in seen:
            continue
        if await offer_has_queued_email(session, int(user_id), oid, contact_email):
            seen.add(oid)
            out.append(off)
    return out


async def offer_allowed_for_incoming_contact(
    session,
    user_id: int,
    offer_id: int,
    contact_email: str,
) -> bool:
    if await offer_was_mailed_to(session, int(user_id), int(offer_id), contact_email):
        return True
    return await offer_has_queued_email(
        session, int(user_id), int(offer_id), contact_email
    )


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
    in_norm = _norm_subject(subject).lower()

    for log, off in rows:
        sent_norm = _norm_subject(log.mail_subject or "").lower()
        if sent_norm and in_norm and sent_norm == in_norm:
            link = (offer_effective_link(off) or "").strip()
            if link:
                return off, "mailing_same_subject"

    if subj_needle:
        best: tuple[float, MailingSendLog, Offer] | None = None
        for log, off in rows:
            if not incoming_subject_binds_offer(subject, off):
                continue
            sc = subject_match_score(subject, off)
            if sc <= 0:
                continue
            if best is None or sc > best[0]:
                best = (sc, log, off)
        if best and best[0] >= 22.0:
            _log, off = best[1], best[2]
            link = (offer_effective_link(off) or "").strip()
            if link:
                return off, "mailing_subject_score"

        for log, off in rows:
            if subject_title_agrees(subject, off):
                link = (offer_effective_link(off) or "").strip()
                if link:
                    return off, "mailing_subject"
            sent_subj = (log.mail_subject or "").strip()
            if sent_subj and subj_needle.lower() in sent_subj.lower():
                link = (offer_effective_link(off) or "").strip()
                if link:
                    return off, "mailing_sent_subject"
            ot = (offer_effective_title(off) or "").strip()
            if ot and subj_needle.lower() in ot.lower():
                link = (offer_effective_link(off) or "").strip()
                if link:
                    return off, "mailing_title"

    unique_ids = {int(off.id) for _log, off in rows}
    if len(unique_ids) == 1:
        _log, off = rows[0]
        if subj_needle and subject_is_informative(subject) and not subject_title_agrees(subject, off):
            if not incoming_subject_binds_offer(subject, off):
                return None, ""
        link = (offer_effective_link(off) or "").strip()
        if link:
            return off, "mailing_only_offer"

    if subj_needle and subject_is_informative(subject):
        if not any(incoming_subject_binds_offer(subject, off) for _log, off in rows[:24]):
            return None, ""

    return None, ""
