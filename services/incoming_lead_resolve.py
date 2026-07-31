"""Привязка входящего только если на этот email был /send (mailing_send_log)."""

from __future__ import annotations

from models import Offer
from services.mailing_send_log import (
    has_mailing_send_for_contact,
    offer_was_mailed_to,
    resolve_inbound_from_send_log,
)
from services.offer_matching import (
    _load_conversation_link,
    _load_offer,
    find_offer_from_incoming_dialog,
)
from services.offer_storage import (
    list_offers_for_validated_contact_email,
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
) -> str:
    if pinned_subj:
        return pinned_subj
    _off, _link, out_subj, _how = await resolve_inbound_from_send_log(
        session,
        user_id=int(user_id),
        contact_email=contact_email,
        inbox_email=inbox_email,
        pinned_offer_id=pinned_offer_id,
    )
    return (out_subj or "").strip()


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

    if not await has_mailing_send_for_contact(session, int(user_id), contact_email):
        return None, "", "", empty_snap

    pinned: int | None = int(resolved_offer_id) if resolved_offer_id else None
    pinned_subj = ""
    conv = None
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

    off, link, out_subj, how = await resolve_inbound_from_send_log(
        session,
        user_id=int(user_id),
        contact_email=contact_email,
        inbox_email=(inbox_email or "").strip(),
        pinned_offer_id=pinned,
    )

    if not off and pinned:
        off = await _offer_from_id(session, user_id=int(user_id), offer_id=int(pinned))
        if off:
            link = (offer_effective_link(off) or "").strip()
            if link:
                how = "pinned_offer_id"
                out_subj = await _resolve_outgoing_subject(
                    session,
                    user_id=int(user_id),
                    contact_email=contact_email,
                    inbox_email=(inbox_email or "").strip(),
                    pinned_offer_id=pinned,
                    pinned_subj=pinned_subj,
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
            out_subj = await _resolve_outgoing_subject(
                session,
                user_id=int(user_id),
                contact_email=contact_email,
                inbox_email=(inbox_email or "").strip(),
                pinned_offer_id=int(off.id),
                pinned_subj=pinned_subj,
            )

    if not off:
        mailed_offers: list[Offer] = []
        for cand in await list_offers_for_validated_contact_email(
            session,
            user_id=int(user_id),
            contact_email=contact_email,
            limit=40,
        ):
            if await offer_was_mailed_to(
                session, int(user_id), int(cand.id), contact_email
            ):
                mailed_offers.append(cand)
        if pinned:
            for cand in mailed_offers:
                if int(cand.id) == int(pinned):
                    off = cand
                    how = "validated_email_pinned"
                    break
        if not off and len(mailed_offers) == 1:
            off = mailed_offers[0]
            how = "validated_email_single"
        if off:
            link = (offer_effective_link(off) or "").strip()
            out_subj = await _resolve_outgoing_subject(
                session,
                user_id=int(user_id),
                contact_email=contact_email,
                inbox_email=(inbox_email or "").strip(),
                pinned_offer_id=int(off.id),
                pinned_subj=pinned_subj,
            )

    if off and link:
        if pinned_subj:
            out_subj = pinned_subj
        snap = _snapshot_from_mailed_offer(off, outgoing_mail_subject=out_subj)
        return off, link, how, snap

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
