"""Входящая почта v2 — см. docs/incoming-mail-rebuild.md (шаг 2: OfferEmail)."""

from __future__ import annotations

from models import Offer
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
        if off:
            link = (offer_effective_link(off) or "").strip()
            snap = _snapshot_from_mailed_offer(off)
            snap["mailing_bound"] = True
            return off, link, "stored_offer_id", snap

    from services.incoming_validated_offer import resolve_inbound_by_validated_email

    off, how = await resolve_inbound_by_validated_email(
        session,
        int(user_id),
        contact_email,
        subject=(subject or "").strip(),
        body_text=(body_text or "").strip(),
    )
    if off:
        link = (offer_effective_link(off) or "").strip()
        snap = _snapshot_from_mailed_offer(off)
        snap["mailing_bound"] = True
        return off, link, how or "validated_email", snap

    return None, "", "", empty_snap
