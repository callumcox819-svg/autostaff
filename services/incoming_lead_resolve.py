"""Привязка входящего письма к лоту — как lead_resolve в poputka88."""

from __future__ import annotations

from models import Offer
from services.mailing_send_log import find_offer_from_mailing_log, offer_was_mailed_to
from services.offer_matching import (
    _load_conversation_link,
    find_offer_from_incoming_dialog,
    incoming_subject_binds_offer,
    is_seller_reply_subject,
    offer_display_title,
    resolve_listing_for_incoming_mail,
    subject_is_informative,
    subject_title_agrees,
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
    if "ricardo.ch" in u:
        return "ricardo.ch"
    if "tutti.ch" in u:
        return "tutti.ch"
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
    Лот только из MailingSendLog (отправлено на этот email) + тема Re:/Aw:.
    """
    snap: dict = {
        "product_title": "",
        "offer_price": "",
        "photo_url": "",
        "service_label": "",
        "mailing_bound": False,
    }

    subj = (subject or "").strip()

    if mailing_bound and resolved_offer_id:
        from services.offer_matching import _load_offer

        off = await _load_offer(session, user_id=int(user_id), offer_id=int(resolved_offer_id))
        if off:
            link = (offer_effective_link(off) or "").strip()
            mailed = await offer_was_mailed_to(
                session, int(user_id), int(off.id), contact_email
            )
            if link and mailed:
                if subject_is_informative(subj) and not subject_title_agrees(subj, off):
                    if not incoming_subject_binds_offer(subj, off):
                        pass
                    else:
                        snap = _snapshot_from_offer(subj, off, mailing_bound=True)
                        return off, link, "mailing_bound", snap
                else:
                    snap = _snapshot_from_offer(subj, off, mailing_bound=True)
                    return off, link, "mailing_bound", snap

    off, how = await find_offer_from_mailing_log(
        session, int(user_id), contact_email, subject
    )
    if off and incoming_subject_binds_offer(subj, off):
        link = (offer_effective_link(off) or "").strip()
        if link:
            snap = _snapshot_from_offer(subject, off, mailing_bound=True)
            return off, link, how, snap

    if subject_is_informative(subj):
        off_subj, link_subj = await resolve_listing_for_incoming_mail(
            session,
            user_id=int(user_id),
            from_email=contact_email,
            subject=subj,
            from_name=from_name,
            body_text=body_text,
            resolved_offer_id=resolved_offer_id,
            mail_ad_url=mail_ad_url,
            inbox_email=inbox_email,
            mailed_only=True,
        )
        if off_subj and link_subj and incoming_subject_binds_offer(subj, off_subj):
            mailed = await offer_was_mailed_to(
                session, int(user_id), int(off_subj.id), contact_email
            )
            if mailed:
                snap = _snapshot_from_offer(
                    subj,
                    off_subj,
                    mailing_bound=_reply_bound(how="subject_mailed", subject=subj, mailed=True),
                )
                return off_subj, link_subj, "subject_mailed", snap

    off_d, how_d = await find_offer_from_incoming_dialog(
        session,
        int(user_id),
        contact_email,
        inbox_email=inbox_email or "",
        subject=subject,
    )
    if off_d and incoming_subject_binds_offer(subj, off_d):
        mailed = await offer_was_mailed_to(session, int(user_id), int(off_d.id), contact_email)
        if mailed:
            link = (offer_effective_link(off_d) or "").strip()
            if link:
                snap = _snapshot_from_offer(subject, off_d, mailing_bound=True)
                return off_d, link, how_d, snap

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
                if off and incoming_subject_binds_offer(subject, off):
                    mailed = await offer_was_mailed_to(
                        session, int(user_id), int(off.id), contact_email
                    )
                    if mailed:
                        link = (offer_effective_link(off) or curl).strip()
                        if link:
                            snap = _snapshot_from_offer(
                                subject,
                                off,
                                mailing_bound=_reply_bound(
                                    how="conversation",
                                    subject=subject,
                                    mailed=True,
                                    has_conv_anchor=bool(getattr(conv, "tg_message_id", None)),
                                ),
                            )
                            return off, link, "conversation", snap

    return None, "", "", snap


def _snapshot_from_offer(subject: str, offer: Offer, *, mailing_bound: bool) -> dict:
    link = (offer_effective_link(offer) or "").strip()
    price = (offer_effective_price(offer, default="") or "").strip()
    photo = (offer_effective_photo(offer) or "").strip()
    bound = mailing_bound
    if subject_is_informative(subject) and not subject_title_agrees(subject, offer):
        bound = False
    return {
        "product_title": offer_display_title(subject, offer, mailing_bound=bound),
        "offer_price": price,
        "photo_url": photo,
        "service_label": _service_label_from_link(link) or "",
        "mailing_bound": bound,
    }
