"""Входящая почта v2 — см. docs/incoming-mail-rebuild.md (шаг 2: OfferEmail)."""

from __future__ import annotations

from models import Offer
from services.offer_matching import incoming_subject_binds_offer, subject_is_informative
from services.offer_storage import (
    normalize_incoming_seller_email,
    offer_effective_link,
    offer_effective_photo,
    offer_effective_price,
    offer_effective_title,
)


def _service_label_from_link(link: str) -> str | None:
    u = (link or "").lower()
    if "ricardo.ch" in u:
        return "ricardo.ch"
    if "tutti.ch" in u:
        return "tutti.ch"
    return None


def _snapshot_from_mailed_offer(
    offer: Offer,
    *,
    outgoing_mail_subject: str = "",
) -> dict:
    link = (offer_effective_link(offer) or "").strip()
    return {
        "product_title": (offer_effective_title(offer) or "").strip(),
        "offer_price": (offer_effective_price(offer, default="") or "").strip(),
        "photo_url": (offer_effective_photo(offer) or "").strip(),
        "service_label": _service_label_from_link(link) or "",
        "outgoing_mail_subject": (outgoing_mail_subject or "").strip(),
        "mailing_bound": True,
    }


def inbound_thread_binds_offer(
    subject: str,
    body_text: str,
    offer: Offer | None,
) -> bool:
    """Re:/цитата называют другой товар — не показываем лот только по OfferEmail."""
    if not offer:
        return False
    from services.subject_offer import inbound_subject_is_weak_for_bind, subjects_for_inbound_resolve

    saw_strong = False
    for subj_try in subjects_for_inbound_resolve(subject or "", body_text or ""):
        if inbound_subject_is_weak_for_bind(subj_try):
            continue
        if not subject_is_informative(subj_try):
            continue
        saw_strong = True
        if incoming_subject_binds_offer(subj_try, offer):
            return True
    if not saw_strong:
        return True
    return False


async def _resolve_offer_from_mailing_thread(
    session,
    *,
    user_id: int,
    contact_email: str,
    subject: str,
    body_text: str,
    inbox_email: str | None,
) -> tuple[Offer | None, str]:
    from services.mailing_send_log import resolve_fi_inbound_offer

    off, how = await resolve_fi_inbound_offer(
        session,
        int(user_id),
        contact_email,
        subject=(subject or "").strip(),
        body_text=(body_text or "").strip(),
        inbox_email=(inbox_email or "").strip(),
    )
    if off and inbound_thread_binds_offer(subject, body_text, off):
        return off, how or "mailing_log_subject"
    return None, ""


def _finish_lead(
    off: Offer,
    how: str,
    *,
    outgoing_mail_subject: str = "",
) -> tuple[Offer, str, str, dict]:
    link = (offer_effective_link(off) or "").strip()
    snap = _snapshot_from_mailed_offer(off, outgoing_mail_subject=outgoing_mail_subject)
    snap["mailing_bound"] = True
    return off, link, how, snap


async def is_incoming_seller_lead(
    session,
    user_id: int,
    contact_email: str,
) -> bool:
    contact_email = normalize_incoming_seller_email(contact_email)
    if not contact_email:
        return False
    from services.offer_storage import _offers_from_offer_email_rows

    hits = await _offers_from_offer_email_rows(
        session, user_id=int(user_id), contact_email=contact_email
    )
    return bool(hits)


async def _resolve_outgoing_subject(
    session,
    *,
    user_id: int,
    contact_email: str,
    inbox_email: str,
    pinned_offer_id: int | None,
    pinned_subj: str,
    offer: Offer | None = None,
    mail_subject: str = "",
) -> str:
    return (pinned_subj or mail_subject or "").strip()


async def resolve_offer_from_validated_seller_email(
    session,
    *,
    user_id: int,
    contact_email: str,
    subject: str = "",
    body_text: str = "",
    pinned_offer_id: int | None = None,
) -> tuple[Offer | None, str, str]:
    return None, "", ""


async def prior_resolved_offer_id_for_seller(
    session,
    *,
    user_id: int,
    contact_email: str,
    exclude_mail_id: int | None = None,
) -> int | None:
    """Повторное письмо: тот же validated email уже был привязан к лоту."""
    from sqlalchemy import func, select as sa_select

    from models import IncomingMail

    contact = normalize_incoming_seller_email(contact_email)
    if not contact:
        return None
    q = (
        sa_select(IncomingMail.resolved_offer_id)
        .where(IncomingMail.user_id == int(user_id))
        .where(func.lower(IncomingMail.from_email) == contact)
        .where(IncomingMail.resolved_offer_id.isnot(None))
        .order_by(IncomingMail.id.desc())
        .limit(1)
    )
    if exclude_mail_id:
        q = q.where(IncomingMail.id != int(exclude_mail_id))
    oid = (await session.execute(q)).scalar_one_or_none()
    try:
        return int(oid) if oid else None
    except (TypeError, ValueError):
        return None


async def resolve_offer_for_incoming_lead(
    session,
    *,
    user_id: int,
    contact_email: str,
    subject: str = "",
    from_name: str = "",
    body_text: str = "",
    resolved_offer_id: int | None = None,
    mail_ad_url: str | None = None,
    inbox_email: str | None = None,
    mailing_bound: bool = False,
) -> tuple[Offer | None, str, str, dict]:
    empty_snap: dict = {
        "product_title": "",
        "offer_price": "",
        "photo_url": "",
        "service_label": "",
        "outgoing_mail_subject": "",
        "mailing_bound": False,
    }

    contact_email = normalize_incoming_seller_email(contact_email)
    if not contact_email:
        return None, "", "", empty_snap

    if resolved_offer_id:
        from services.offer_matching import _load_offer

        off = await _load_offer(
            session, user_id=int(user_id), offer_id=int(resolved_offer_id)
        )
        if off and inbound_thread_binds_offer(subject, body_text, off):
            return _finish_lead(off, "stored_offer_id")

    off_mail, how_mail = await _resolve_offer_from_mailing_thread(
        session,
        user_id=int(user_id),
        contact_email=contact_email,
        subject=subject,
        body_text=body_text,
        inbox_email=inbox_email,
    )
    if off_mail:
        return _finish_lead(off_mail, how_mail)

    from services.incoming_validated_offer import resolve_inbound_by_validated_email

    off, how = await resolve_inbound_by_validated_email(
        session,
        int(user_id),
        contact_email,
        subject=(subject or "").strip(),
        body_text=(body_text or "").strip(),
    )
    if off and inbound_thread_binds_offer(subject, body_text, off):
        return _finish_lead(off, how or "validated_email")

    prior_oid = await prior_resolved_offer_id_for_seller(
        session,
        user_id=int(user_id),
        contact_email=contact_email,
    )
    if prior_oid:
        from services.offer_matching import _load_offer

        off_p = await _load_offer(
            session, user_id=int(user_id), offer_id=int(prior_oid)
        )
        if off_p and inbound_thread_binds_offer(subject, body_text, off_p):
            return _finish_lead(off_p, "prior_inbound_same_seller")

    from services.offer_storage import find_offer_for_mailed_seller_reply

    off_fb = await find_offer_for_mailed_seller_reply(
        session,
        user_id=int(user_id),
        contact_email=contact_email,
        subject=(subject or "").strip(),
        body_text=(body_text or "").strip(),
        inbox_email=(inbox_email or "").strip(),
    )
    if off_fb and inbound_thread_binds_offer(subject, body_text, off_fb):
        return _finish_lead(off_fb, "mailed_seller_reply")

    return None, "", "", empty_snap
