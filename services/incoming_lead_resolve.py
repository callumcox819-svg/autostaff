"""Привязка входящего письма к лоту — email продавца после ValidEmail (= OFFER в рассылке)."""

from __future__ import annotations

from models import Offer
from services.mailing_send_log import (
    find_latest_mailed_offer_for_recipient,
    offer_allowed_for_incoming_contact,
    offer_was_mailed_to,
)
from services.offer_matching import offer_display_title
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


async def _resolve_from_validated_seller_email(
    session,
    *,
    user_id: int,
    contact_email: str,
) -> tuple[Offer | None, str, str]:
    """
    Лот только по validated_emails / OfferEmail для from_email продавца.
    Тема Re: (OFFER в шаблоне) — для отображения, не для поиска лота.
    """
    pool = await list_offers_for_validated_contact_email(
        session, user_id=int(user_id), contact_email=contact_email, limit=80
    )
    if not pool:
        return None, "", ""

    if len(pool) == 1:
        only = pool[0]
        link = (offer_effective_link(only) or "").strip()
        if link:
            return only, link, "validated_email"
        return None, "", ""

    pool_ids = {int(o.id) for o in pool}
    mailed = await find_latest_mailed_offer_for_recipient(
        session,
        int(user_id),
        contact_email,
        offer_ids=pool_ids,
    )
    if mailed:
        link = (offer_effective_link(mailed) or "").strip()
        if link:
            return mailed, link, "validated_email_mailing"

    newest = pool[0]
    link = (offer_effective_link(newest) or "").strip()
    if link:
        return newest, link, "validated_email_newest"
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
    """(offer, listing_url, matched_by, snapshot) — лот по email валидации, не по теме письма."""
    snap: dict = {
        "product_title": "",
        "offer_price": "",
        "photo_url": "",
        "service_label": "",
        "mailing_bound": False,
    }

    subj = (subject or "").strip()
    contact_email = normalize_incoming_seller_email(contact_email)
    if not contact_email:
        return None, "", "", snap

    if mailing_bound and resolved_offer_id:
        from services.offer_matching import _load_offer

        off = await _load_offer(session, user_id=int(user_id), offer_id=int(resolved_offer_id))
        if off:
            link = (offer_effective_link(off) or "").strip()
            if link and await offer_allowed_for_incoming_contact(
                session, int(user_id), int(off.id), contact_email, from_name=from_name
            ):
                snap = _snapshot_from_offer(subj, off, bind_by_seller_email=True)
                return off, link, "mailing_bound", snap

    off_em, link_em, how_em = await _resolve_from_validated_seller_email(
        session,
        user_id=int(user_id),
        contact_email=contact_email,
    )
    if off_em and link_em:
        snap = _snapshot_from_offer(subj, off_em, bind_by_seller_email=True)
        return off_em, link_em, how_em, snap

    off_log = await find_latest_mailed_offer_for_recipient(
        session, int(user_id), contact_email, offer_ids=None
    )
    if off_log:
        link = (offer_effective_link(off_log) or "").strip()
        if link:
            snap = _snapshot_from_offer(subj, off_log, bind_by_seller_email=True)
            return off_log, link, "mailing_log_email", snap

    return None, "", "", snap


def _snapshot_from_offer(
    subject: str,
    offer: Offer,
    *,
    mailing_bound: bool = False,
    bind_by_seller_email: bool = False,
) -> dict:
    """Карточка: название/фото/цена из OFFER (БД), если лот найден по email продавца."""
    link = (offer_effective_link(offer) or "").strip()
    price = (offer_effective_price(offer, default="") or "").strip()
    photo = (offer_effective_photo(offer) or "").strip()
    subj = (subject or "").strip()

    if bind_by_seller_email or mailing_bound:
        db_title = (offer_effective_title(offer) or "").strip()
        product_title = db_title or offer_display_title(subj, offer, mailing_bound=True)
        return {
            "product_title": product_title,
            "offer_price": price,
            "photo_url": photo,
            "service_label": _service_label_from_link(link) or "",
            "mailing_bound": True,
        }

    product_title = offer_display_title(subj, offer, mailing_bound=False)
    return {
        "product_title": product_title,
        "offer_price": price,
        "photo_url": photo,
        "service_label": _service_label_from_link(link) or "",
        "mailing_bound": False,
    }
