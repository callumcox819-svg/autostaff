"""Входящее письмо: лот только по validated email (OfferEmail), 1 почта → 1 объявление."""

from __future__ import annotations

from models import Offer
from services.offer_storage import (
    _offers_from_offer_email_rows,
    normalize_incoming_seller_email,
    offer_effective_link,
    offer_effective_photo,
    offer_effective_price,
    offer_effective_title,
    parse_offer_raw,
)


def seller_person_name(offer: Offer | None) -> str:
    if not offer:
        return ""
    raw = parse_offer_raw(getattr(offer, "raw_json", None))
    for key in ("item_person_name", "person_name", "seller_name"):
        v = str(raw.get(key) or "").strip()
        if v:
            return v
    return (getattr(offer, "person_name", None) or "").strip()


def inbound_card_inbox_label(
    offer: Offer | None,
    *,
    buyer_display_name: str = "",
) -> str:
    """«Gnimor (Anna Kerher)» — продавец из JSON + имя рассылки пользователя."""
    seller = seller_person_name(offer)
    buyer = (buyer_display_name or "").strip()
    if seller and buyer and seller.lower() != buyer.lower():
        return f"{seller} ({buyer})"
    if seller:
        return seller
    return buyer


def offer_inbound_snapshot(offer: Offer) -> dict:
    link = (offer_effective_link(offer) or "").strip()
    svc = ""
    if "ricardo.ch" in link.lower():
        svc = "ricardo.ch"
    elif "tutti.ch" in link.lower():
        svc = "tutti.ch"
    return {
        "product_title": (offer_effective_title(offer) or "").strip(),
        "offer_price": (offer_effective_price(offer, default="") or "").strip(),
        "photo_url": (offer_effective_photo(offer) or "").strip(),
        "service_label": svc,
        "listing_url": link,
    }


async def resolve_inbound_by_validated_email(
    session,
    user_id: int,
    seller_email: str,
    *,
    subject: str = "",
    body_text: str = "",
) -> tuple[Offer | None, str]:
    """
    From = email продавца → лот(ы) из OfferEmail и validated_emails в offers.raw_json.
    Один лot — сразу; несколько — по теме Re:/цитате.
    """
    from services.offer_storage import (
        find_single_offer_for_seller_contact_email,
        list_offers_for_validated_contact_email,
    )

    contact = normalize_incoming_seller_email(seller_email) or (seller_email or "").strip().lower()
    if not contact:
        return None, ""

    hits = await list_offers_for_validated_contact_email(
        session, user_id=int(user_id), contact_email=contact, limit=40
    )
    from services.incoming_lead_resolve import inbound_thread_binds_offer
    from services.offer_matching import subject_is_informative

    if len(hits) == 1:
        only = hits[0]
        if inbound_thread_binds_offer(subject, body_text, only):
            return only, "validated_email_one_lot"
        if not subject_is_informative(subject):
            return only, "validated_email_one_lot"
    if len(hits) > 1:
        pick = await find_single_offer_for_seller_contact_email(
            session,
            user_id=int(user_id),
            contact_email=contact,
            subject=(subject or "").strip(),
            body_text=(body_text or "").strip(),
        )
        if pick:
            return pick, "validated_email_multi_subject"
        return None, ""

    hits = await _offers_from_offer_email_rows(
        session, user_id=int(user_id), contact_email=contact
    )
    if len(hits) == 1:
        only = hits[0]
        if inbound_thread_binds_offer(subject, body_text, only):
            return only, "validated_email_one_lot"
        if not subject_is_informative(subject):
            return only, "validated_email_one_lot"
    return None, ""
