"""Привязка входящего письма к лоту — как lead_resolve в poputka88."""

from __future__ import annotations

from models import Offer
from services.mailing_send_log import (
    find_offer_from_mailing_log,
    list_allowed_offers_for_incoming_contact,
    offer_allowed_for_incoming_contact,
    offer_was_mailed_to,
)
from services.offer_matching import (
    _load_conversation_link,
    _pick_offer_by_subject_in_list,
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
    list_offers_for_validated_contact_email,
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
    if how in ("listing", "subject_only", "conversation", "validated", "validated_email", "legacy_subject", "catalog_subject", "title_needle") and is_seller_reply_subject(subject):
        return True
    return False


def _service_label_from_link(link: str) -> str | None:
    u = (link or "").lower()
    if "ricardo.ch" in u:
        return "ricardo.ch"
    if "tutti.ch" in u:
        return "tutti.ch"
    return None


def _mailing_log_match_ok(subject: str, off: Offer, how: str) -> bool:
    if not (how or "").startswith("mailing"):
        return False
    if not subject_is_informative(subject):
        return True
    return incoming_subject_binds_offer(subject, off)


async def _resolve_from_validated_email_offers(
    session,
    *,
    user_id: int,
    contact_email: str,
    subject: str,
) -> tuple[Offer | None, str, str]:
    """Лот по validated_emails в raw_json (источник правды после VOID + ValidEmail)."""
    subj = (subject or "").strip()
    pool = await list_offers_for_validated_contact_email(
        session, user_id=int(user_id), contact_email=contact_email, limit=80
    )
    if not pool:
        return None, "", ""

    if subject_is_informative(subj):
        hit = _pick_offer_by_subject_in_list(pool, subj)
        if hit and incoming_subject_binds_offer(subj, hit):
            link = (offer_effective_link(hit) or "").strip()
            if link:
                return hit, link, "validated_email_subject"
        for cand in pool:
            if incoming_subject_binds_offer(subj, cand):
                link = (offer_effective_link(cand) or "").strip()
                if link:
                    return cand, link, "validated_email_subject"
        return None, "", ""

    if len(pool) == 1:
        only = pool[0]
        link = (offer_effective_link(only) or "").strip()
        if link:
            return only, link, "validated_email"

    return None, "", ""


async def _resolve_from_allowed_offers(
    session,
    *,
    user_id: int,
    contact_email: str,
    subject: str,
    from_name: str = "",
) -> tuple[Offer | None, str, str]:
    """Журнал рассылки + OfferEmail на этот contact; лот по теме Re:/Kaufinteresse."""
    subj = (subject or "").strip()
    allowed = await list_allowed_offers_for_incoming_contact(
        session, int(user_id), contact_email, from_name=from_name or "", limit=80
    )
    if not allowed:
        return None, "", ""

    if subject_is_informative(subj):
        hit = _pick_offer_by_subject_in_list(allowed, subj)
        if hit:
            link = (offer_effective_link(hit) or "").strip()
            if link:
                return hit, link, "validated_subject"
        for cand in allowed:
            if incoming_subject_binds_offer(subj, cand):
                link = (offer_effective_link(cand) or "").strip()
                if link:
                    return cand, link, "validated_subject"

    if len(allowed) == 1:
        only = allowed[0]
        link = (offer_effective_link(only) or "").strip()
        if not link:
            return None, "", ""
        if subject_is_informative(subj) and not incoming_subject_binds_offer(subj, only):
            return None, "", ""
        return only, link, "validated_single"

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
    """
    (offer, listing_url, matched_by, snapshot)
    Лот: рассылка (log) или очередь OfferEmail на этот email + тема письма.
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
            if link and await offer_allowed_for_incoming_contact(
                session, int(user_id), int(off.id), contact_email, from_name=from_name
            ):
                if not subject_is_informative(subj) or incoming_subject_binds_offer(subj, off):
                    snap = _snapshot_from_offer(subj, off, mailing_bound=True)
                    return off, link, "mailing_bound", snap

    # Источник правды после ValidEmail: один email → один лот (OfferEmail + validated_emails).
    off_em, link_em, how_em = await _resolve_from_validated_email_offers(
        session,
        user_id=int(user_id),
        contact_email=contact_email,
        subject=subj,
    )
    if off_em and link_em:
        snap = _snapshot_from_offer(subj, off_em, mailing_bound=True)
        snap["mailing_bound"] = True
        return off_em, link_em, how_em, snap

    off, how = await find_offer_from_mailing_log(
        session, int(user_id), contact_email, subject
    )
    if off:
        link = (offer_effective_link(off) or "").strip()
        if link and (
            _mailing_log_match_ok(subj, off, how)
            or incoming_subject_binds_offer(subj, off)
        ):
            snap = _snapshot_from_offer(subject, off, mailing_bound=True)
            return off, link, how, snap

    off_v, link_v, how_v = await _resolve_from_allowed_offers(
        session,
        user_id=int(user_id),
        contact_email=contact_email,
        subject=subj,
        from_name=from_name or "",
    )
    if off_v and link_v:
        mailed = await offer_was_mailed_to(session, int(user_id), int(off_v.id), contact_email)
        snap = _snapshot_from_offer(
            subj,
            off_v,
            mailing_bound=_reply_bound(how="validated", subject=subj, mailed=mailed),
        )
        return off_v, link_v, how_v, snap

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
            if await offer_allowed_for_incoming_contact(
                session, int(user_id), int(off_subj.id), contact_email, from_name=from_name
            ):
                mailed = await offer_was_mailed_to(
                    session, int(user_id), int(off_subj.id), contact_email
                )
                snap = _snapshot_from_offer(
                    subj,
                    off_subj,
                    mailing_bound=_reply_bound(how="subject_mailed", subject=subj, mailed=mailed),
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
        if await offer_allowed_for_incoming_contact(
            session, int(user_id), int(off_d.id), contact_email, from_name=from_name
        ):
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
                    if await offer_allowed_for_incoming_contact(
                        session, int(user_id), int(off.id), contact_email, from_name=from_name
                    ):
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

    if subject_is_informative(subj) and is_seller_reply_subject(subj):
        validated_pool = await list_offers_for_validated_contact_email(
            session,
            user_id=int(user_id),
            contact_email=contact_email,
            limit=80,
        )
        if len(validated_pool) > 1:
            return None, "", "", snap

        from services.offer_storage import find_offer_by_subject_and_seller_hint

        off_legacy = await find_offer_by_subject_and_seller_hint(
            session,
            user_id=int(user_id),
            contact_email=contact_email,
            from_name=from_name or "",
            subject=subj,
        )
        if off_legacy:
            link = (offer_effective_link(off_legacy) or "").strip()
            if link:
                mailed = await offer_was_mailed_to(
                    session, int(user_id), int(off_legacy.id), contact_email
                )
                snap = _snapshot_from_offer(
                    subj,
                    off_legacy,
                    mailing_bound=_reply_bound(
                        how="legacy_subject",
                        subject=subj,
                        mailed=mailed,
                    ),
                )
                return off_legacy, link, "legacy_subject", snap

        from services.offer_matching import find_offer_by_catalog_subject_match

        off_cat = await find_offer_by_catalog_subject_match(
            session,
            user_id=int(user_id),
            subject=subj,
        )
        if off_cat:
            link = (offer_effective_link(off_cat) or "").strip()
            if link:
                mailed = await offer_was_mailed_to(
                    session, int(user_id), int(off_cat.id), contact_email
                )
                snap = _snapshot_from_offer(
                    subj,
                    off_cat,
                    mailing_bound=_reply_bound(
                        how="catalog_subject",
                        subject=subj,
                        mailed=mailed,
                    ),
                )
                return off_cat, link, "catalog_subject", snap

        from services.offer_storage import find_offer_by_product_title_in_subject

        off_needle = await find_offer_by_product_title_in_subject(
            session,
            user_id=int(user_id),
            subject=subj,
            contact_email=contact_email,
        )
        if off_needle:
            link = (offer_effective_link(off_needle) or "").strip()
            if link:
                snap = _snapshot_from_offer(subj, off_needle, mailing_bound=True)
                snap["mailing_bound"] = True
                return off_needle, link, "title_needle", snap

    return None, "", "", snap


def _snapshot_from_offer(subject: str, offer: Offer, *, mailing_bound: bool) -> dict:
    link = (offer_effective_link(offer) or "").strip()
    price = (offer_effective_price(offer, default="") or "").strip()
    photo = (offer_effective_photo(offer) or "").strip()
    from services.offer_storage import offer_effective_title

    bound = mailing_bound
    if bound:
        db_title = (offer_effective_title(offer) or "").strip()
        product_title = db_title or offer_display_title(subject, offer, mailing_bound=True)
    else:
        if subject_is_informative(subject) and not subject_title_agrees(subject, offer):
            if not incoming_subject_binds_offer(subject, offer):
                bound = False
        product_title = offer_display_title(subject, offer, mailing_bound=bound)
    return {
        "product_title": product_title,
        "offer_price": price,
        "photo_url": photo,
        "service_label": _service_label_from_link(link) or "",
        "mailing_bound": bool(mailing_bound),
    }
