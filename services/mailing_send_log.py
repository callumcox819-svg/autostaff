"""Журнал успешных отправок — как recipients.lead_id в poputka88."""

from __future__ import annotations

from sqlalchemy import func, or_, select

from models import MailingSendLog, Offer
from services.offer_matching import (
    _pick_offer_by_subject_in_list,
    canon_seller_email,
    incoming_subject_binds_offer,
    product_title_from_subject,
    subject_is_informative,
    subject_match_score,
    subject_title_agrees,
    _norm_subject,
)
from services.offer_storage import offer_effective_link, offer_effective_title


def _canon_recipient(email: str) -> str:
    return canon_seller_email((email or "").strip())


async def record_mailing_send(
    session,
    *,
    user_id: int,
    offer_id: int,
    recipient_email: str,
    mail_subject: str = "",
    from_account_email: str = "",
    offer_email_id: int | None = None,
) -> None:
    """Записать: этому email ушло письмо по конкретному offer_id."""
    from services.offer_storage import normalize_incoming_seller_email

    rcpt = normalize_incoming_seller_email(recipient_email) or _canon_recipient(recipient_email)
    if not rcpt or not int(offer_id or 0):
        return
    row = MailingSendLog(
        user_id=int(user_id),
        offer_id=int(offer_id),
        recipient_email=rcpt,
        mail_subject=(mail_subject or "").strip()[:500] or None,
        from_account_email=(from_account_email or "").strip().lower()[:255] or None,
        offer_email_id=int(offer_email_id) if offer_email_id else None,
    )
    session.add(row)


async def _mailing_log_rows_for_recipient(
    session,
    user_id: int,
    contact_email: str,
    *,
    limit: int = 400,
) -> list[tuple[MailingSendLog, Offer]]:
    """Строки журнала рассылки на этот email (канонизация gmail/+alias)."""
    email = _canon_recipient(contact_email)
    if not email:
        return []

    raw = (contact_email or "").strip().lower()
    conds = [func.lower(MailingSendLog.recipient_email) == email]
    if raw and raw != email:
        conds.append(func.lower(MailingSendLog.recipient_email) == raw)

    rows = (
        await session.execute(
            select(MailingSendLog, Offer)
            .join(Offer, Offer.id == MailingSendLog.offer_id)
            .where(MailingSendLog.user_id == int(user_id))
            .where(or_(*conds))
            .order_by(MailingSendLog.sent_at.desc(), MailingSendLog.id.desc())
            .limit(int(limit))
        )
    ).all()

    if rows:
        return list(rows)

    # Старые записи могли сохраниться без канонизации — добираем из недавних отправок.
    broad = (
        await session.execute(
            select(MailingSendLog, Offer)
            .join(Offer, Offer.id == MailingSendLog.offer_id)
            .where(MailingSendLog.user_id == int(user_id))
            .order_by(MailingSendLog.sent_at.desc(), MailingSendLog.id.desc())
            .limit(int(limit))
        )
    ).all()
    out: list[tuple[MailingSendLog, Offer]] = []
    for log, off in broad:
        if _canon_recipient(log.recipient_email or "") == email:
            out.append((log, off))
    return out


async def list_offers_from_mailing_log(
    session,
    user_id: int,
    contact_email: str,
    *,
    limit: int = 80,
) -> list[Offer]:
    """Все лоты, на которые рассылали этому продавцу (после purge OfferEmail)."""
    rows = await _mailing_log_rows_for_recipient(session, user_id, contact_email, limit=400)
    seen: set[int] = set()
    out: list[Offer] = []
    for _log, off in rows:
        oid = int(off.id)
        if oid in seen:
            continue
        seen.add(oid)
        out.append(off)
        if len(out) >= int(limit):
            break
    return out


async def resolve_inbound_from_send_log(
    session,
    *,
    user_id: int,
    contact_email: str,
    inbox_email: str = "",
    pinned_offer_id: int | None = None,
) -> tuple[Offer | None, str, str, str]:
    """
    Входящее → лот и тема исходящего письма (/send), без разбора Re:.
    Returns: (offer, listing_url, outgoing_mail_subject, matched_by)
    """
    rows = await _mailing_log_rows_for_recipient(session, int(user_id), contact_email, limit=400)
    inbox = (inbox_email or "").strip().lower()

    def _pick(log: MailingSendLog, off: Offer) -> tuple[Offer | None, str, str, str]:
        link = (offer_effective_link(off) or "").strip()
        if not link:
            return None, "", "", ""
        out_subj = (log.mail_subject or "").strip()
        return off, link, out_subj, "mailing_send_log"

    def _oldest_hit(
        pairs: list[tuple[MailingSendLog, Offer]],
    ) -> tuple[Offer | None, str, str, str]:
        """Первая рассылка в треде (не последняя), чтобы 2–5 ответ не прыгали на другой лот."""
        for log, off in reversed(pairs):
            hit = _pick(log, off)
            if hit[0]:
                return hit
        return None, "", "", ""

    if pinned_offer_id and int(pinned_offer_id or 0):
        pid = int(pinned_offer_id)
        matched: list[tuple[MailingSendLog, Offer]] = []
        for log, off in rows:
            if int(off.id) != pid:
                continue
            if inbox:
                sent_from = (log.from_account_email or "").strip().lower()
                if sent_from and sent_from != inbox:
                    continue
            hit = _pick(log, off)
            if hit[0]:
                matched.append((log, off))
        if matched:
            hit = _oldest_hit(matched)
            if hit[0]:
                return hit[0], hit[1], hit[2], "mailing_send_log_pinned"
        from services.offer_matching import _load_offer

        off = await _load_offer(session, user_id=int(user_id), offer_id=pid)
        if off:
            link = (offer_effective_link(off) or "").strip()
            if link:
                return off, link, "", "mailing_send_log_pinned"

    if inbox:
        inbox_rows: list[tuple[MailingSendLog, Offer]] = []
        for log, off in rows:
            sent_from = (log.from_account_email or "").strip().lower()
            if sent_from and sent_from != inbox:
                continue
            hit = _pick(log, off)
            if hit[0]:
                inbox_rows.append((log, off))
        if inbox_rows:
            hit = _oldest_hit(inbox_rows)
            if hit[0]:
                return hit[0], hit[1], hit[2], hit[3]

    if rows:
        hit = _oldest_hit(rows)
        if hit[0]:
            return hit[0], hit[1], hit[2], hit[3]

    return None, "", "", ""


async def has_mailing_send_for_contact(
    session,
    user_id: int,
    contact_email: str,
) -> bool:
    """Был ли /send на этот email продавца (иначе не лид)."""
    rows = await _mailing_log_rows_for_recipient(session, int(user_id), contact_email, limit=3)
    return bool(rows)


async def find_latest_mailed_offer_for_recipient(
    session,
    user_id: int,
    contact_email: str,
    *,
    offer_ids: set[int] | None = None,
) -> Offer | None:
    """Последний лот из журнала рассылки на этот email (без матча по теме Re:)."""
    rows = await _mailing_log_rows_for_recipient(session, int(user_id), contact_email, limit=400)
    for _log, off in rows:
        oid = int(off.id)
        if offer_ids is not None and oid not in offer_ids:
            continue
        if (offer_effective_link(off) or "").strip():
            return off
    return None


async def offer_was_mailed_to(
    session,
    user_id: int,
    offer_id: int,
    contact_email: str,
) -> bool:
    email = _canon_recipient(contact_email)
    if not email or not int(offer_id or 0):
        return False
    rows = (
        await session.execute(
            select(MailingSendLog)
            .where(MailingSendLog.user_id == int(user_id))
            .where(MailingSendLog.offer_id == int(offer_id))
            .order_by(MailingSendLog.sent_at.desc(), MailingSendLog.id.desc())
            .limit(40)
        )
    ).scalars().all()
    return any(_canon_recipient(r.recipient_email or "") == email for r in rows)


async def offer_has_queued_email(
    session,
    user_id: int,
    offer_id: int,
    contact_email: str,
) -> bool:
    """OfferEmail ещё в очереди /send (до purge после отправки)."""
    from sqlalchemy import func, or_, select

    from models import Offer, OfferEmail

    email = _canon_recipient(contact_email)
    if not email or not int(offer_id or 0):
        return False
    raw = (contact_email or "").strip().lower()
    conds = [func.lower(OfferEmail.email) == email]
    if raw and raw != email:
        conds.append(func.lower(OfferEmail.email) == raw)
    row = (
        await session.execute(
            select(OfferEmail.id)
            .join(Offer, Offer.id == OfferEmail.offer_id)
            .where(Offer.user_id == int(user_id))
            .where(OfferEmail.offer_id == int(offer_id))
            .where(or_(*conds))
            .limit(1)
        )
    ).scalar_one_or_none()
    return row is not None


async def list_allowed_offers_for_incoming_contact(
    session,
    user_id: int,
    contact_email: str,
    *,
    from_name: str = "",
    limit: int = 80,
) -> list[Offer]:
    """Лоты: журнал рассылки, email в JSON, очередь, имя продавца (legacy)."""
    from services.offer_matching import list_offers_for_seller_email
    from services.offer_storage import (
        list_offers_for_seller_contact_hints,
        list_offers_for_validated_contact_email,
    )

    seen: set[int] = set()
    out: list[Offer] = []
    for off in await list_offers_from_mailing_log(
        session, int(user_id), contact_email, limit=limit
    ):
        oid = int(off.id)
        if oid in seen:
            continue
        seen.add(oid)
        out.append(off)
    for off in await list_offers_for_validated_contact_email(
        session, user_id=int(user_id), contact_email=contact_email, limit=limit
    ):
        oid = int(off.id)
        if oid in seen:
            continue
        seen.add(oid)
        out.append(off)
    for off in await list_offers_for_seller_email(
        session, user_id=int(user_id), from_email=contact_email
    ):
        oid = int(off.id)
        if oid in seen:
            continue
        if await offer_has_queued_email(session, int(user_id), oid, contact_email):
            seen.add(oid)
            out.append(off)
    for off in await list_offers_for_seller_contact_hints(
        session,
        user_id=int(user_id),
        contact_email=contact_email,
        from_name=from_name or "",
        limit=limit,
    ):
        oid = int(off.id)
        if oid in seen:
            continue
        seen.add(oid)
        out.append(off)
    return out


async def offer_allowed_for_incoming_contact(
    session,
    user_id: int,
    offer_id: int,
    contact_email: str,
    *,
    from_name: str = "",
) -> bool:
    if await offer_was_mailed_to(session, int(user_id), int(offer_id), contact_email):
        return True
    if await offer_has_queued_email(
        session, int(user_id), int(offer_id), contact_email
    ):
        return True
    from services.offer_storage import offer_has_seller_contact, offer_has_validated_email

    if await offer_has_validated_email(
        session,
        user_id=int(user_id),
        offer_id=int(offer_id),
        contact_email=contact_email,
    ):
        return True
    return await offer_has_seller_contact(
        session,
        user_id=int(user_id),
        offer_id=int(offer_id),
        contact_email=contact_email,
        from_name=from_name or "",
    )


async def find_offer_from_mailing_log(
    session,
    user_id: int,
    contact_email: str,
    subject: str = "",
) -> tuple[Offer | None, str]:
    """
    Лот из последней рассылки на этот email (poputka: get_lead_for_mailing_recipient).
    Если несколько — уточняем по теме Re:.
    """
    rows = await _mailing_log_rows_for_recipient(session, user_id, contact_email, limit=400)

    if not rows:
        return None, ""

    subj_needle = product_title_from_subject(subject)
    in_norm = _norm_subject(subject).lower()
    in_product = (subj_needle or "").strip().lower()

    for log, off in rows:
        sent_norm = _norm_subject(log.mail_subject or "").lower()
        if sent_norm and in_norm and sent_norm == in_norm:
            link = (offer_effective_link(off) or "").strip()
            if link:
                return off, "mailing_same_subject"

    if in_product:
        for log, off in rows:
            sent_product = product_title_from_subject(log.mail_subject or "").lower()
            if not sent_product:
                continue
            if (
                in_product == sent_product
                or in_product in sent_product
                or sent_product in in_product
            ):
                link = (offer_effective_link(off) or "").strip()
                if link:
                    return off, "mailing_product_thread"

    if subj_needle:
        best: tuple[float, MailingSendLog, Offer] | None = None
        for log, off in rows:
            if not incoming_subject_binds_offer(subject, off):
                continue
            sc = subject_match_score(subject, off)
            if sc <= 0:
                continue
            if best is None or sc > best[0]:
                best = (sc, log, off)
        if best and best[0] >= 22.0:
            _log, off = best[1], best[2]
            link = (offer_effective_link(off) or "").strip()
            if link:
                return off, "mailing_subject_score"

        for log, off in rows:
            if subject_title_agrees(subject, off):
                link = (offer_effective_link(off) or "").strip()
                if link:
                    return off, "mailing_subject"
            sent_subj = (log.mail_subject or "").strip()
            if sent_subj and subj_needle.lower() in sent_subj.lower():
                link = (offer_effective_link(off) or "").strip()
                if link:
                    return off, "mailing_sent_subject"
            ot = (offer_effective_title(off) or "").strip()
            if ot and subj_needle.lower() in ot.lower():
                link = (offer_effective_link(off) or "").strip()
                if link:
                    return off, "mailing_title"

    unique_ids = {int(off.id) for _log, off in rows}
    if len(unique_ids) == 1:
        _log, off = rows[0]
        if subj_needle and subject_is_informative(subject) and not subject_title_agrees(subject, off):
            if not incoming_subject_binds_offer(subject, off):
                return None, ""
        link = (offer_effective_link(off) or "").strip()
        if link:
            return off, "mailing_only_offer"

    if subj_needle and subject_is_informative(subject):
        bound = [
            off
            for _log, off in rows[:48]
            if incoming_subject_binds_offer(subject, off)
        ]
        if bound:
            hit = _pick_offer_by_subject_in_list(bound, subject)
            if hit:
                link = (offer_effective_link(hit) or "").strip()
                if link:
                    return hit, "mailing_subject_pick"

    return None, ""
