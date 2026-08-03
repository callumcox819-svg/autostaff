"""1 email продавца → 1 лот (validated + журнал /send). Без каталога и fuzzy."""

from __future__ import annotations

from models import MailingSendLog, Offer
from services.mailing_send_log import (
    _mailing_log_rows_for_recipient,
    find_offer_from_mailing_log,
)
from services.offer_storage import (
    _offers_from_offer_email_rows,
    normalize_incoming_seller_email,
    offer_effective_title,
    offer_incoming_bindable,
)


def _offer_matches_needle(off: Offer, needle: str) -> bool:
    from services.offer_matching import (
        _distinctive_listing_tokens,
        _offer_title_matches_needle,
        distinctive_token_in_title,
        incoming_subject_binds_offer,
    )

    n = (needle or "").strip()
    if len(n) < 4:
        return False
    title = (offer_effective_title(off) or "").strip()
    if not title:
        return False
    if incoming_subject_binds_offer(n, off) or incoming_subject_binds_offer(f"Re: {n}", off):
        return True
    if _offer_title_matches_needle(n.lower(), title.lower()):
        return True
    head = n.split(" - ")[0].split(" – ")[0].strip()
    if head and head != n and _offer_title_matches_needle(head.lower(), title.lower()):
        return True
    nt = _distinctive_listing_tokens(n.lower())
    title_l = title.lower()
    if len(nt) >= 2:
        hits = sum(1 for t in nt if distinctive_token_in_title(t, title_l))
        if hits >= 2:
            return True
    return False


def _pool_unique(validated: list[Offer], mailed: list[Offer]) -> list[Offer]:
    out: list[Offer] = []
    seen: set[int] = set()
    for off in (*validated, *mailed):
        oid = int(off.id)
        if oid in seen:
            continue
        seen.add(oid)
        out.append(off)
    return out


def _single_lot_allowed(
    off: Offer,
    *,
    subject: str,
    body_text: str,
) -> bool:
    """Не подставлять Hemnes, если в Re:/теле явно Sonnen Lampe."""
    from services.offer_matching import subject_is_informative
    from services.subject_offer import primary_inbound_product_needle

    subj = (subject or "").strip()
    if not subject_is_informative(subj) and not (body_text or "").strip():
        return True
    needle = primary_inbound_product_needle(subj, body_text or "")
    if not needle:
        return True
    return _offer_matches_needle(off, needle)


async def resolve_strict_seller_inbound_offer(
    session,
    user_id: int,
    contact_email: str,
    *,
    subject: str = "",
    body_text: str = "",
) -> tuple[Offer | None, str]:
    """
    From = email продавца. Лот только из OfferEmail + MailingSendLog на этот email.
    Re:/цитата с OFFER важнее «единственного» лота на адрес.
    """
    contact = normalize_incoming_seller_email(contact_email) or (contact_email or "").strip().lower()
    if not contact:
        return None, ""

    from services.offer_matching import incoming_subject_binds_offer, subject_is_informative
    from services.subject_offer import (
        inbound_body_product_needle,
        inbound_subject_is_weak_for_bind,
        primary_inbound_product_needle,
        subjects_for_inbound_resolve,
    )

    validated = await _offers_from_offer_email_rows(
        session, user_id=int(user_id), contact_email=contact
    )
    validated = [o for o in validated if offer_incoming_bindable(o)] or validated

    rows: list[tuple[MailingSendLog, Offer]] = await _mailing_log_rows_for_recipient(
        session, int(user_id), contact, limit=200
    )
    mailed_offers: list[Offer] = []
    seen_m: set[int] = set()
    for _log, off in rows:
        if not off:
            continue
        oid = int(off.id)
        if oid in seen_m:
            continue
        seen_m.add(oid)
        mailed_offers.append(off)

    pool = _pool_unique(validated, mailed_offers)
    allowed_ids = {int(o.id) for o in pool}

    for subj_try in subjects_for_inbound_resolve(subject or "", body_text or ""):
        if inbound_subject_is_weak_for_bind(subj_try):
            continue
        if not subject_is_informative(subj_try):
            continue
        for off in pool:
            if incoming_subject_binds_offer(subj_try, off):
                return off, "strict_subject_binds"
        off, how = await find_offer_from_mailing_log(
            session, int(user_id), contact, subj_try
        )
        if not off:
            continue
        oid = int(off.id)
        if allowed_ids and oid not in allowed_ids:
            binds = incoming_subject_binds_offer(subj_try, off)
            n_chk = primary_inbound_product_needle(subject or "", body_text or "")
            if not binds and not (n_chk and _offer_matches_needle(off, n_chk)):
                continue
        if pool and not incoming_subject_binds_offer(subj_try, off):
            needle = primary_inbound_product_needle(subject or "", body_text or "")
            if needle and not _offer_matches_needle(off, needle):
                continue
        return off, how or "strict_mailing_subject"

    needle = primary_inbound_product_needle(subject or "", body_text or "")
    if needle:
        from services.offer_matching import offer_needle_is_too_generic

        for off in pool:
            if _offer_matches_needle(off, needle):
                return off, "strict_inbound_needle"
        if not offer_needle_is_too_generic(needle):
            for subj_try in subjects_for_inbound_resolve(subject or "", body_text or ""):
                if inbound_subject_is_weak_for_bind(subj_try):
                    continue
                if not subject_is_informative(subj_try):
                    continue
                off, how = await find_offer_from_mailing_log(
                    session, int(user_id), contact, subj_try
                )
                if not off:
                    continue
                if incoming_subject_binds_offer(subj_try, off) or _offer_matches_needle(
                    off, needle
                ):
                    return off, how or "strict_mailing_needle"
        return None, ""

    body_needle = inbound_body_product_needle(body_text or "")
    if body_needle:
        for off in pool:
            if _offer_matches_needle(off, body_needle):
                return off, "strict_body_quote"
        return None, ""

    if len(validated) == 1 and not mailed_offers:
        off = validated[0]
        if _single_lot_allowed(off, subject=subject, body_text=body_text):
            return off, "strict_validated_email"

    if len(mailed_offers) == 1 and not validated:
        off = mailed_offers[0]
        if _single_lot_allowed(off, subject=subject, body_text=body_text):
            return off, "strict_mailing_log_single"

    if len(validated) == 1 and len(mailed_offers) == 1:
        if int(validated[0].id) == int(mailed_offers[0].id):
            off = validated[0]
            if _single_lot_allowed(off, subject=subject, body_text=body_text):
                return off, "strict_validated_and_mailed"
        off = mailed_offers[0]
        if _single_lot_allowed(off, subject=subject, body_text=body_text):
            return off, "strict_mailing_over_validated_mismatch"

    if len(validated) == 1:
        off = validated[0]
        if _single_lot_allowed(off, subject=subject, body_text=body_text):
            return off, "strict_validated_fallback"

    if len(mailed_offers) == 1:
        off = mailed_offers[0]
        if _single_lot_allowed(off, subject=subject, body_text=body_text):
            return off, "strict_mailing_fallback"

    return None, ""
