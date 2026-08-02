"""Привязка входящего к лоту: validated email продавца и/или журнал рассылки."""

from __future__ import annotations

from models import Offer
from services.mailing_send_log import (
    find_offer_from_mailing_log,
    has_mailing_send_for_contact,
    resolve_inbound_from_send_log,
)
from services.offer_matching import (
    _load_conversation_link,
    _load_offer,
    find_offer_from_incoming_dialog,
    incoming_subject_binds_offer,
    subject_is_informative,
)
from services.offer_storage import (
    find_offer_for_mailed_seller_reply,
    find_single_offer_for_seller_contact_email,
    inbound_seller_offer_pool,
    normalize_incoming_seller_email,
    offer_effective_link,
    offer_effective_photo,
    offer_effective_price,
    offer_effective_title,
    offer_incoming_bindable,
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
    if await inbound_seller_offer_pool(
        session, user_id=int(user_id), contact_email=contact_email, limit=4
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
    subject: str = "",
    body_text: str = "",
    pinned_offer_id: int | None = None,
) -> tuple[Offer | None, str, str]:
    """Лот по OfferEmail / validated_emails (+ полная тема OFFER при нескольких)."""
    from services.offer_matching import incoming_subject_binds_offer, subject_is_informative

    contact_email = normalize_incoming_seller_email(contact_email)
    if not contact_email:
        return None, "", ""

    subj = (subject or "").strip()
    subj_strong = subject_is_informative(subj)
    pid = int(pinned_offer_id) if pinned_offer_id else None
    if pid and subj_strong:
        pinned_off = await _offer_from_id(session, user_id=int(user_id), offer_id=pid)
        if pinned_off and incoming_subject_binds_offer(subj, pinned_off):
            return (
                pinned_off,
                (offer_effective_link(pinned_off) or "").strip(),
                "validated_seller_email_pinned",
            )

    off = await find_single_offer_for_seller_contact_email(
        session,
        user_id=int(user_id),
        contact_email=contact_email,
        subject=subj,
        body_text=body_text or "",
    )
    if not off:
        return None, "", ""
    return off, (offer_effective_link(off) or "").strip(), "validated_seller_email"


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
    if pinned:
        stored = await _offer_from_id(session, user_id=int(user_id), offer_id=pinned)
        if stored and offer_incoming_bindable(stored):
            link = (offer_effective_link(stored) or "").strip()
            out_subj = await _resolve_outgoing_subject(
                session,
                user_id=int(user_id),
                contact_email=contact_email,
                inbox_email=(inbox_email or "").strip(),
                pinned_offer_id=pinned,
                pinned_subj="",
                offer=stored,
                mail_subject=subject or "",
            )
            snap = _snapshot_from_mailed_offer(stored, outgoing_mail_subject=out_subj)
            return stored, link, "stored_resolved_offer_id", snap

    conv_pin: int | None = None
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
                conv_pin = int(conv.pinned_offer_id)
            pinned_subj = (getattr(conv, "pinned_outgoing_subject", None) or "").strip()

    subj_strong = subject_is_informative(subject or "")

    async def _offer_if_pin_ok(offer_id: int | None) -> Offer | None:
        if not offer_id:
            return None
        o = await _offer_from_id(session, user_id=int(user_id), offer_id=int(offer_id))
        if not o:
            return None
        if subj_strong and not incoming_subject_binds_offer(subject or "", o):
            return None
        return o

    validated_hit = await find_single_offer_for_seller_contact_email(
        session,
        user_id=int(user_id),
        contact_email=contact_email,
        subject=subject or "",
        body_text=body_text or "",
    )
    has_send = await has_mailing_send_for_contact(session, int(user_id), contact_email)

    seller_pool_cache: list[Offer] | None = None

    async def _get_seller_pool() -> list[Offer]:
        nonlocal seller_pool_cache
        if seller_pool_cache is None:
            seller_pool_cache = await inbound_seller_offer_pool(
                session, user_id=int(user_id), contact_email=contact_email, limit=20
            )
        return seller_pool_cache

    has_seller_binding = bool(validated_hit) or has_send
    if not has_seller_binding:
        from services.offer_matching import is_seller_reply_subject

        if is_seller_reply_subject(subject or ""):
            has_seller_binding = bool(await _get_seller_pool())

    if validated_hit and offer_incoming_bindable(validated_hit):
        fi = validated_hit
    elif has_seller_binding:
        fi = await find_offer_for_mailed_seller_reply(
            session,
            user_id=int(user_id),
            contact_email=contact_email,
            subject=subject or "",
            body_text=body_text or "",
            inbox_email=(inbox_email or "").strip(),
        )
    else:
        fi = None

    if fi and offer_incoming_bindable(fi):
        link = (offer_effective_link(fi) or "").strip()
        out_subj = await _resolve_outgoing_subject(
            session,
            user_id=int(user_id),
            contact_email=contact_email,
            inbox_email=(inbox_email or "").strip(),
            pinned_offer_id=int(fi.id),
            pinned_subj=pinned_subj,
            offer=fi,
            mail_subject=subject or "",
        )
        if pinned_subj:
            out_subj = pinned_subj
        snap = _snapshot_from_mailed_offer(fi, outgoing_mail_subject=out_subj)
        return fi, link, "fi_seller_bind", snap

    off: Offer | None = None
    link = ""
    how = ""

    off, link, how = await resolve_offer_from_validated_seller_email(
        session,
        user_id=int(user_id),
        contact_email=contact_email,
        subject=subject or "",
        body_text=body_text or "",
        pinned_offer_id=pinned,
    )

    if not off and has_send and (subject or "").strip():
        off, how = await find_offer_from_mailing_log(
            session,
            int(user_id),
            contact_email,
            subject or "",
        )
        if off:
            link = (offer_effective_link(off) or "").strip()
            how = how or "mailing_subject"

    if not off and has_send:
        off, link, _out_subj, how = await resolve_inbound_from_send_log(
            session,
            user_id=int(user_id),
            contact_email=contact_email,
            inbox_email=(inbox_email or "").strip(),
            pinned_offer_id=pinned,
            subject=subject or "",
        )
        if not off:
            off, link, _out_subj, how = await resolve_inbound_from_send_log(
                session,
                user_id=int(user_id),
                contact_email=contact_email,
                inbox_email="",
                pinned_offer_id=pinned,
                subject=subject or "",
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

    if not off:
        for pin_id in (pinned, conv_pin):
            o = await _offer_if_pin_ok(pin_id)
            if o:
                off = o
                link = (offer_effective_link(o) or "").strip()
                how = "pinned_offer_id"
                break
        if not off and not subj_strong:
            for pin_id in (pinned, conv_pin):
                o = await _offer_from_id(session, user_id=int(user_id), offer_id=int(pin_id or 0))
                if o:
                    off = o
                    link = (offer_effective_link(o) or "").strip()
                    how = "pinned_offer_id"
                    break

    if not off and has_seller_binding:
        from services.offer_storage import _pick_offer_from_inbound_subjects

        seller_pool = await _get_seller_pool()
        if seller_pool:
            pick = _pick_offer_from_inbound_subjects(
                seller_pool,
                subject=subject or "",
                body_text=body_text or "",
            )
            if pick:
                off = pick
                link = (offer_effective_link(pick) or "").strip()
                how = how or "offer_subject_seller_pool"

    if not off and not has_seller_binding:
        return None, "", "", empty_snap

    if off and not link:
        link = (offer_effective_link(off) or "").strip()

    if (not off or not link) and has_seller_binding:
        from services.offer_matching import resolve_listing_for_incoming_mail
        from services.subject_offer import subjects_for_inbound_resolve

        for subj_try in subjects_for_inbound_resolve(subject or "", body_text or ""):
            off2, link2 = await resolve_listing_for_incoming_mail(
                session,
                user_id=int(user_id),
                from_email=contact_email,
                subject=subj_try,
                from_name=from_name or "",
                body_text=body_text or "",
                resolved_offer_id=pinned or (int(off.id) if off else None),
                mail_ad_url=mail_ad_url,
                inbox_email=(inbox_email or "").strip(),
                mailed_only=True,
            )
            if off2 and (link2 or off2):
                off = off2
                link = (link2 or "").strip() or (offer_effective_link(off2) or "").strip()
                how = how or "listing_mailed_only"
                break

    if off:
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
