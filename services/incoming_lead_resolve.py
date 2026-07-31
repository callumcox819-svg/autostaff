"""Привязка входящего к лоту: validated email продавца и/или журнал рассылки."""

from __future__ import annotations

from models import Offer
from services.mailing_send_log import (
    has_mailing_send_for_contact,
    resolve_inbound_from_send_log,
)
from services.offer_matching import (
    _load_conversation_link,
    _load_offer,
    find_offer_from_incoming_dialog,
)
from services.offer_storage import (
    find_single_offer_for_seller_contact_email,
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


async def is_incoming_seller_lead(
    session,
    user_id: int,
    contact_email: str,
) -> bool:
    """Лид = validated/OfferEmail в БД или был /send на этот email."""
    contact_email = normalize_incoming_seller_email(contact_email)
    if not contact_email:
        return False
    if await find_single_offer_for_seller_contact_email(
        session, user_id=int(user_id), contact_email=contact_email
    ):
        return True
    return await has_mailing_send_for_contact(session, int(user_id), contact_email)


async def _offer_from_id(
    session,
    *,
    user_id: int,
    offer_id: int,
) -> Offer | None:
    if not int(offer_id or 0):
        return None
    return await _load_offer(session, user_id=int(user_id), offer_id=int(offer_id))


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
    if pinned_subj:
        return pinned_subj
    if await has_mailing_send_for_contact(session, int(user_id), contact_email):
        _off, _link, out_subj, _how = await resolve_inbound_from_send_log(
            session,
            user_id=int(user_id),
            contact_email=contact_email,
            inbox_email=inbox_email,
            pinned_offer_id=pinned_offer_id,
        )
        if (out_subj or "").strip():
            return out_subj.strip()
    if offer:
        from services.subject_offer import pick_mailing_subject

        ot = (offer_effective_title(offer) or "").strip()
        if ot:
            return pick_mailing_subject(ot)
    return (mail_subject or "").strip()


async def resolve_offer_from_validated_seller_email(
    session,
    *,
    user_id: int,
    contact_email: str,
    pinned_offer_id: int | None = None,
) -> tuple[Offer | None, str, str]:
    """Лот по validated_emails / OfferEmail — приоритет над темой Re:."""
    contact_email = normalize_incoming_seller_email(contact_email)
    if not contact_email:
        return None, "", ""

    pid = int(pinned_offer_id) if pinned_offer_id else None
    if pid:
        pinned_off = await _offer_from_id(session, user_id=int(user_id), offer_id=pid)
        if pinned_off:
            link = (offer_effective_link(pinned_off) or "").strip()
            if link:
                return pinned_off, link, "validated_seller_email_pinned"

    off = await find_single_offer_for_seller_contact_email(
        session,
        user_id=int(user_id),
        contact_email=contact_email,
    )
    if not off:
        return None, "", ""
    link = (offer_effective_link(off) or "").strip()
    if not link:
        return None, "", ""
    return off, link, "validated_seller_email"


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

    pinned: int | None = int(resolved_offer_id) if resolved_offer_id else None
    pinned_subj = ""
    if (inbox_email or "").strip() and contact_email:
        conv = await _load_conversation_link(
            session,
            user_id=int(user_id),
            inbox_email=(inbox_email or "").strip(),
            contact_email=contact_email,
        )
        if conv:
            if getattr(conv, "pinned_offer_id", None):
                pinned = int(conv.pinned_offer_id)
            pinned_subj = (getattr(conv, "pinned_outgoing_subject", None) or "").strip()

    validated_hit = await find_single_offer_for_seller_contact_email(
        session, user_id=int(user_id), contact_email=contact_email
    )
    has_send = await has_mailing_send_for_contact(session, int(user_id), contact_email)

    off: Offer | None = None
    link = ""
    how = ""

    if pinned:
        off = await _offer_from_id(session, user_id=int(user_id), offer_id=int(pinned))
        if off:
            link = (offer_effective_link(off) or "").strip()
            if link:
                how = "pinned_offer_id"

    if not off:
        off, link, how = await resolve_offer_from_validated_seller_email(
            session,
            user_id=int(user_id),
            contact_email=contact_email,
            pinned_offer_id=pinned,
        )

    if not off and has_send:
        off, link, _out_subj, how = await resolve_inbound_from_send_log(
            session,
            user_id=int(user_id),
            contact_email=contact_email,
            inbox_email=(inbox_email or "").strip(),
            pinned_offer_id=pinned,
        )
        if not off:
            off, link, _out_subj, how = await resolve_inbound_from_send_log(
                session,
                user_id=int(user_id),
                contact_email=contact_email,
                inbox_email="",
                pinned_offer_id=pinned,
            )

    if not off:
        off, how = await find_offer_from_incoming_dialog(
            session,
            int(user_id),
            contact_email,
            inbox_email=(inbox_email or "").strip(),
            subject=subject or "",
        )
        if off:
            link = (offer_effective_link(off) or "").strip()
            how = how or "incoming_dialog"

    if not off and not validated_hit and not has_send:
        return None, "", "", empty_snap

    if off and not link:
        link = (offer_effective_link(off) or "").strip()

    if off and link:
        out_subj = await _resolve_outgoing_subject(
            session,
            user_id=int(user_id),
            contact_email=contact_email,
            inbox_email=(inbox_email or "").strip(),
            pinned_offer_id=int(off.id),
            pinned_subj=pinned_subj,
            offer=off,
            mail_subject=subject or "",
        )
        if pinned_subj:
            out_subj = pinned_subj
        snap = _snapshot_from_mailed_offer(off, outgoing_mail_subject=out_subj)
        return off, link, how or "seller_lead", snap

    return None, "", "", empty_snap


def _snapshot_from_offer(
    subject: str,
    offer: Offer,
    *,
    mailing_bound: bool = False,
    bind_by_seller_email: bool = False,
    outgoing_mail_subject: str = "",
) -> dict:
    snap = _snapshot_from_mailed_offer(
        offer,
        outgoing_mail_subject=outgoing_mail_subject or (subject or "").strip(),
    )
    if not (bind_by_seller_email or mailing_bound):
        snap["mailing_bound"] = False
    return snap
