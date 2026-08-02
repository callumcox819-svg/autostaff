"""Единая привязка входящего письма продавца к лоту (IMAP, карточка, «Создать ссылку»)."""

from __future__ import annotations

from models import Offer
from services.incoming_lead_resolve import (
    _snapshot_from_mailed_offer,
    resolve_offer_for_incoming_lead,
)
from services.offer_storage import (
    find_offer_by_product_title_in_subject,
    find_offer_for_mailed_seller_reply,
    list_offers_for_validated_contact_email,
    normalize_incoming_seller_email,
    offer_effective_link,
    offer_effective_title,
)


async def force_bind_incoming_seller_offer(
    session,
    *,
    user_id: int,
    contact_email: str,
    subject: str = "",
    body_text: str = "",
    from_name: str = "",
    inbox_email: str = "",
    mail_ad_url: str | None = None,
    resolved_offer_id: int | None = None,
    mailing_bound: bool = False,
) -> tuple[Offer | None, str, str, dict]:
    """
    FI-логика: email продавца + журнал /send + validated → лот, title/photo/price в snap.
    Returns: offer, listing_url, how, snapshot dict.
    """
    contact = normalize_incoming_seller_email(contact_email) or (contact_email or "").strip().lower()
    empty_snap: dict = {
        "product_title": "",
        "offer_price": "",
        "photo_url": "",
        "service_label": "",
        "outgoing_mail_subject": "",
        "mailing_bound": False,
    }
    if not contact:
        return None, "", "", empty_snap

    off, link, how, snap = await resolve_offer_for_incoming_lead(
        session,
        user_id=int(user_id),
        contact_email=contact,
        subject=(subject or "").strip(),
        from_name=(from_name or "").strip(),
        body_text=(body_text or "").strip(),
        resolved_offer_id=resolved_offer_id,
        mail_ad_url=mail_ad_url,
        inbox_email=(inbox_email or "").strip(),
        mailing_bound=mailing_bound,
    )
    link = (link or "").strip()
    if off:
        if not link:
            link = (offer_effective_link(off) or "").strip()
        return off, link, how or "resolve_lead", snap

    off = await find_offer_for_mailed_seller_reply(
        session,
        user_id=int(user_id),
        contact_email=contact,
        subject=(subject or "").strip(),
        body_text=(body_text or "").strip(),
        inbox_email=(inbox_email or "").strip(),
    )
    if off:
        link = (offer_effective_link(off) or "").strip()
        return off, link, "mailed_seller_reply", _snapshot_from_mailed_offer(off)

    from services.mailing_send_log import (
        bindable_offers_for_mailing_recipient,
        find_latest_mailed_offer_for_recipient,
        has_mailing_send_for_contact,
        list_allowed_offers_for_incoming_contact,
        list_offers_from_mailing_log,
    )

    if await has_mailing_send_for_contact(session, int(user_id), contact):
        mailed = await list_offers_from_mailing_log(
            session, int(user_id), contact, limit=24
        )
        if len(mailed) == 1:
            off = mailed[0]
        elif mailed:
            off = await find_latest_mailed_offer_for_recipient(
                session, int(user_id), contact
            )
        else:
            bound = await bindable_offers_for_mailing_recipient(
                session, int(user_id), contact
            )
            if len(bound) == 1:
                off = bound[0]
            elif bound:
                off = bound[0]
        if off:
            link = (offer_effective_link(off) or "").strip()
            return off, link, "mailing_log_force", _snapshot_from_mailed_offer(off)

    validated = await list_offers_for_validated_contact_email(
        session, user_id=int(user_id), contact_email=contact, limit=12
    )
    if len(validated) == 1:
        off = validated[0]
        link = (offer_effective_link(off) or "").strip()
        return off, link, "validated_single", _snapshot_from_mailed_offer(off)

    from services.offer_matching import is_seller_reply_subject, product_title_from_subject
    from services.subject_offer import subjects_for_inbound_resolve

    if is_seller_reply_subject(subject or ""):
        for subj_try in subjects_for_inbound_resolve(subject or "", body_text or ""):
            off = await find_offer_by_product_title_in_subject(
                session,
                user_id=int(user_id),
                subject=subj_try,
                contact_email=contact,
            )
            if off:
                link = (offer_effective_link(off) or "").strip()
                return off, link, "subject_title", _snapshot_from_mailed_offer(off)

        needle = (product_title_from_subject(subject or "") or "").strip().lower()
        if len(needle) >= 4:
            pool = validated or await list_offers_from_mailing_log(
                session, int(user_id), contact, limit=40
            )
            for cand in pool:
                title = (offer_effective_title(cand) or "").strip().lower()
                if title and (needle in title or title in needle):
                    link = (offer_effective_link(cand) or "").strip()
                    return (
                        cand,
                        link,
                        "subject_needle_pool",
                        _snapshot_from_mailed_offer(cand),
                    )

    allowed = await list_allowed_offers_for_incoming_contact(
        session, int(user_id), contact, from_name=(from_name or "").strip(), limit=40
    )
    if len(allowed) == 1:
        off = allowed[0]
        link = (offer_effective_link(off) or "").strip()
        return off, link, "allowed_single", _snapshot_from_mailed_offer(off)

    return None, "", "", empty_snap
