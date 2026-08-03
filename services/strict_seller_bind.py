"""1 email продавца → 1 лот (validated + журнал /send). Без каталога и fuzzy."""

from __future__ import annotations

from models import Offer
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
    from services.offer_matching import _offer_title_matches_needle, incoming_subject_binds_offer

    n = (needle or "").strip()
    if len(n) < 4:
        return False
    title = (offer_effective_title(off) or "").strip()
    if not title:
        return False
    if incoming_subject_binds_offer(n, off) or incoming_subject_binds_offer(f"Re: {n}", off):
        return True
    return _offer_title_matches_needle(n.lower(), title.lower())


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
    Цитата OFFER в теле важнее Re: и «последней» рассылки на адрес.
    """
    contact = normalize_incoming_seller_email(contact_email) or (contact_email or "").strip().lower()
    if not contact:
        return None, ""

    from services.subject_offer import (
        inbound_body_product_needle,
        inbound_subject_is_weak_for_bind,
        subjects_for_inbound_resolve,
    )

    body_needle = inbound_body_product_needle(body_text or "")

    validated = await _offers_from_offer_email_rows(
        session, user_id=int(user_id), contact_email=contact
    )
    validated = [o for o in validated if offer_incoming_bindable(o)] or validated

    rows = await _mailing_log_rows_for_recipient(session, int(user_id), contact, limit=200)
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

    allowed_ids = {int(o.id) for o in validated} | {int(o.id) for o in mailed_offers}

    for subj_try in subjects_for_inbound_resolve(subject or "", body_text or ""):
        if inbound_subject_is_weak_for_bind(subj_try):
            continue
        off, how = await find_offer_from_mailing_log(
            session, int(user_id), contact, subj_try
        )
        if not off:
            continue
        oid = int(off.id)
        if allowed_ids and oid not in allowed_ids:
            continue
        return off, how or "strict_mailing_subject"

    if body_needle and allowed_ids:
        for off in validated + mailed_offers:
            if _offer_matches_needle(off, body_needle):
                return off, "strict_body_quote"
        return None, ""

    if body_needle:
        return None, ""

    if len(validated) == 1 and not mailed_offers:
        return validated[0], "strict_validated_email"

    if len(mailed_offers) == 1 and not validated:
        return mailed_offers[0], "strict_mailing_log_single"

    if len(validated) == 1 and len(mailed_offers) == 1:
        if int(validated[0].id) == int(mailed_offers[0].id):
            return validated[0], "strict_validated_and_mailed"
        return mailed_offers[0], "strict_mailing_over_validated_mismatch"

    if len(validated) == 1:
        return validated[0], "strict_validated_fallback"

    if len(mailed_offers) == 1:
        return mailed_offers[0], "strict_mailing_fallback"

    return None, ""
