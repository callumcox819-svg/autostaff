"""Привязка входящего письма к лоту — как lead_resolve в poputka88."""

from __future__ import annotations

from models import Offer
from services.mailing_send_log import find_offer_from_mailing_log, offer_was_mailed_to
from services.offer_matching import (
    _load_conversation_link,
    find_offer_by_incoming_subject,
    is_seller_reply_subject,
    narkologia_link_title_from_mail,
    resolve_listing_for_incoming_mail,
)
from services.offer_storage import (
    find_offer_by_link,
    offer_effective_link,
    offer_effective_photo,
    offer_effective_price,
)


def _reply_bound(*, how: str, subject: str, mailed: bool = False, has_conv_anchor: bool = False) -> bool:
    if mailed or (how or "").startswith("mailing"):
        return True
    if how == "subject_mailing":
        return True
    if has_conv_anchor and is_seller_reply_subject(subject):
        return True
    if how in ("listing", "subject_only", "conversation") and is_seller_reply_subject(subject):
        return True
    return False


def _service_label_from_link(link: str) -> str | None:
    u = (link or "").lower()
    if "2dehands" in u or "2ememain" in u:
        return "2dehands.be"
    if "bpost" in u:
        return "bpost.be"
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
    """
    (offer, listing_url, matched_by, snapshot)
    snapshot: product_title, offer_price, photo_url, service_label
    """
    snap: dict = {
        "product_title": "",
        "offer_price": "",
        "photo_url": "",
        "service_label": "",
        "mailing_bound": False,
    }

    if mailing_bound and resolved_offer_id:
        from services.offer_matching import _load_offer

        off = await _load_offer(session, user_id=int(user_id), offer_id=int(resolved_offer_id))
        if off:
            link = (offer_effective_link(off) or "").strip()
            if link:
                snap = _snapshot_from_offer(subject, off, mailing_bound=True)
                return off, link, "mailing_bound", snap

    off, how = await find_offer_from_mailing_log(
        session, int(user_id), contact_email, subject
    )
    if off:
        link = (offer_effective_link(off) or "").strip()
        if link:
            snap = _snapshot_from_offer(subject, off, mailing_bound=True)
            return off, link, how, snap

    off, link = await resolve_listing_for_incoming_mail(
        session,
        user_id=int(user_id),
        from_email=contact_email,
        subject=subject,
        from_name=from_name,
        body_text=body_text,
        resolved_offer_id=resolved_offer_id,
        mail_ad_url=mail_ad_url,
        inbox_email=inbox_email,
    )
    if off and link:
        mailed = await offer_was_mailed_to(session, int(user_id), int(off.id), contact_email)
        snap = _snapshot_from_offer(
            subject,
            off,
            mailing_bound=_reply_bound(how="listing", subject=subject, mailed=mailed),
        )
        return off, link, "listing", snap

    off = await find_offer_by_incoming_subject(
        session, int(user_id), subject, from_email=contact_email
    )
    if off:
        link = (offer_effective_link(off) or "").strip()
        if link:
            mailed = await offer_was_mailed_to(
                session, int(user_id), int(off.id), contact_email
            )
            how = "subject_mailing" if mailed else "subject_only"
            snap = _snapshot_from_offer(
                subject,
                off,
                mailing_bound=_reply_bound(how=how, subject=subject, mailed=mailed),
            )
            return off, link, how, snap

    if (inbox_email or "").strip() and (contact_email or "").strip():
        conv = await _load_conversation_link(
            session,
            user_id=int(user_id),
            inbox_email=inbox_email or "",
            contact_email=contact_email,
        )
        if conv:
            curl = (conv.ad_url or "").strip()
            if curl:
                off = await find_offer_by_link(session, user_id=int(user_id), ad_url=curl)
                if off:
                    link = (offer_effective_link(off) or curl).strip()
                    if link:
                        mailed = await offer_was_mailed_to(
                            session, int(user_id), int(off.id), contact_email
                        )
                        snap = _snapshot_from_offer(
                            subject,
                            off,
                            mailing_bound=_reply_bound(
                                how="conversation",
                                subject=subject,
                                mailed=mailed,
                                has_conv_anchor=bool(getattr(conv, "tg_message_id", None)),
                            ),
                        )
                        return off, link, "conversation", snap

    return None, "", "", snap


def _snapshot_from_offer(subject: str, offer: Offer, *, mailing_bound: bool) -> dict:
    link = (offer_effective_link(offer) or "").strip()
    price = (offer_effective_price(offer, default="") or "").strip()
    photo = (offer_effective_photo(offer) or "").strip()
    return {
        "product_title": narkologia_link_title_from_mail(subject, offer),
        "offer_price": price,
        "photo_url": photo,
        "service_label": _service_label_from_link(link) or "",
        "mailing_bound": mailing_bound,
    }
