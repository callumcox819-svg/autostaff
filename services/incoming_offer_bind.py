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
    inbound_seller_offer_pool,
    list_offers_for_validated_contact_email,
    normalize_incoming_seller_email,
    offer_effective_link,
    offer_effective_title,
    _pick_offer_from_inbound_subjects,
)


async def _offer_from_prior_inbound_mail(
    session,
    *,
    user_id: int,
    contact_email: str,
    subject: str,
    exclude_mail_id: int | None = None,
) -> Offer | None:
    """Повторное письмо в том же треде — лот с прошлой карточки этого продавца."""
    from sqlalchemy import func, select as sa_select

    from models import IncomingMail, Offer
    from services.offer_matching import (
        _load_offer,
        incoming_subject_binds_offer,
        product_title_from_subject,
    )

    contact = normalize_incoming_seller_email(contact_email) or (contact_email or "").strip().lower()
    if not contact:
        return None
    needle = (product_title_from_subject(subject or "") or "").strip().lower()
    rows = (
        await session.execute(
            sa_select(IncomingMail)
            .where(IncomingMail.user_id == int(user_id))
            .where(func.lower(IncomingMail.from_email) == contact)
            .where(IncomingMail.resolved_offer_id.isnot(None))
            .order_by(IncomingMail.id.desc())
            .limit(32)
        )
    ).scalars().all()
    for mail in rows:
        if exclude_mail_id and int(mail.id) == int(exclude_mail_id):
            continue
        oid = int(mail.resolved_offer_id or 0)
        if not oid:
            continue
        off = await _load_offer(session, user_id=int(user_id), offer_id=oid)
        if not off:
            continue
        if needle and len(needle) >= 4:
            pt = (
                (getattr(mail, "product_title", None) or "").strip()
                or (offer_effective_title(off) or "").strip()
            ).lower()
            if pt and (needle in pt or pt in needle):
                return off
        if incoming_subject_binds_offer(subject or "", off):
            return off
    return None


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
    exclude_mail_id: int | None = None,
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

    from services.mailing_send_log import has_mailing_send_for_contact, resolve_fi_inbound_offer

    if await has_mailing_send_for_contact(session, int(user_id), contact):
        off_fi, how_fi = await resolve_fi_inbound_offer(
            session,
            int(user_id),
            contact,
            subject=(subject or "").strip(),
            body_text=(body_text or "").strip(),
            inbox_email=(inbox_email or "").strip(),
        )
        if off_fi:
            link = (offer_effective_link(off_fi) or "").strip()
            return off_fi, link, how_fi or "fi_inbound_send_log", _snapshot_from_mailed_offer(off_fi)

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

    off = await _offer_from_prior_inbound_mail(
        session,
        user_id=int(user_id),
        contact_email=contact,
        subject=(subject or "").strip(),
        exclude_mail_id=exclude_mail_id,
    )
    if off:
        from services.offer_matching import incoming_subject_binds_offer
        from services.subject_offer import offer_title_from_inbound_subject

        cur_offer = (offer_title_from_inbound_subject(subject or "") or "").strip()
        if (
            cur_offer
            and len(cur_offer) >= 4
            and not incoming_subject_binds_offer(subject or "", off)
        ):
            off = None
        else:
            link = (offer_effective_link(off) or "").strip()
            return off, link, "prior_inbound_mail", _snapshot_from_mailed_offer(off)

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
        find_offer_from_mailing_log,
        find_offer_from_send_log_by_product_context,
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
            pick = _pick_offer_from_inbound_subjects(
                mailed,
                subject=(subject or "").strip(),
                body_text=(body_text or "").strip(),
            )
            if pick:
                off = pick
            else:
                from services.subject_offer import subjects_for_inbound_resolve

                off = None
                for subj_try in subjects_for_inbound_resolve(subject or "", body_text or ""):
                    off, _ = await find_offer_from_mailing_log(
                        session, int(user_id), contact, subj_try
                    )
                    if off:
                        break
        else:
            bound = await bindable_offers_for_mailing_recipient(
                session, int(user_id), contact
            )
            if len(bound) == 1:
                off = bound[0]
            else:
                off = None
        if off:
            link = (offer_effective_link(off) or "").strip()
            return off, link, "mailing_log_force", _snapshot_from_mailed_offer(off)

    off_ctx, how_ctx = await find_offer_from_send_log_by_product_context(
        session,
        int(user_id),
        subject=(subject or "").strip(),
        body_text=(body_text or "").strip(),
        from_email=contact,
    )
    if off_ctx:
        link = (offer_effective_link(off_ctx) or "").strip()
        return off_ctx, link, how_ctx or "send_log_product_context", _snapshot_from_mailed_offer(off_ctx)

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

    if is_seller_reply_subject(subject or ""):
        needle = (product_title_from_subject(subject or "") or "").strip().lower()
        from services.offer_matching import offer_needle_is_too_generic

        if len(needle) >= 4 and not offer_needle_is_too_generic(needle):
            from sqlalchemy import select as sa_select

            from models import Offer
            from services.offer_matching import (
                _offer_title_matches_needle,
                _pick_offer_by_subject_in_list,
            )
            from services.mailing_send_log import offer_was_mailed_to

            rows = (
                await session.execute(
                    sa_select(Offer)
                    .where(Offer.user_id == int(user_id))
                    .order_by(Offer.id.desc())
                    .limit(4000)
                )
            ).scalars().all()
            hits: list[Offer] = []
            for cand in rows:
                title = (offer_effective_title(cand) or "").strip()
                if title and _offer_title_matches_needle(needle, title):
                    hits.append(cand)
            if hits:
                pick = _pick_offer_by_subject_in_list(hits, subject or "")
                if pick:
                    off = pick
                else:
                    mailed = [
                        h
                        for h in hits
                        if await offer_was_mailed_to(
                            session, int(user_id), int(h.id), contact
                        )
                    ]
                    off = mailed[0] if len(mailed) == 1 else None
                    if not off and len(hits) == 1:
                        off = hits[0]
                link = (offer_effective_link(off) or "").strip()
                return off, link, "catalog_title", _snapshot_from_mailed_offer(off)

    return None, "", "", empty_snap
