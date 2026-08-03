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
from services.offer_storage import offer_effective_link, offer_effective_title, offer_incoming_bindable


def _mailing_return_offer(off: Offer) -> bool:
    return offer_incoming_bindable(off)


def _canon_recipient(email: str) -> str:
    return canon_seller_email((email or "").strip())


_YAHOO_DOMAINS = frozenset({"yahoo.com", "yahoo.de", "ymail.com", "rocketmail.com"})


def seller_emails_equivalent(a: str, b: str) -> bool:
    """Один продавец: переадресация yahoo.de → yahoo.com и т.п."""
    ca = _canon_recipient(a)
    cb = _canon_recipient(b)
    if not ca or not cb:
        return False
    if ca == cb:
        return True
    if "@" not in ca or "@" not in cb:
        return False
    la, da = ca.split("@", 1)
    lb, db = cb.split("@", 1)
    if la != lb:
        return False
    return da in _YAHOO_DOMAINS and db in _YAHOO_DOMAINS


async def find_offer_from_send_log_by_product_context(
    session,
    user_id: int,
    *,
    subject: str,
    body_text: str = "",
    from_email: str = "",
) -> tuple[Offer | None, str]:
    """
    Переадресация: Reply с другого @, но OFFER в теме/цитате = тема /send в журнале.
    """
    from services.offer_matching import _offer_title_matches_needle
    from services.subject_offer import subjects_for_inbound_resolve

    contact = _canon_recipient(from_email)
    local_in = contact.split("@", 1)[0] if "@" in contact else ""

    best: tuple[float, Offer, str] | None = None

    for subj_try in subjects_for_inbound_resolve(subject or "", body_text or ""):
        needle = (product_title_from_subject(subj_try) or "").strip().lower()
        if len(needle) < 4:
            continue
        logs = (
            await session.execute(
                select(MailingSendLog)
                .where(MailingSendLog.user_id == int(user_id))
                .order_by(MailingSendLog.sent_at.desc(), MailingSendLog.id.desc())
                .limit(600)
            )
        ).scalars().all()
        for log in logs:
            off = await _offer_for_mailing_log_row(
                session, int(user_id), log, contact_email=contact or from_email
            )
            if not off:
                continue
            sent_subj = (log.mail_subject or "").strip()
            sent_needle = (product_title_from_subject(sent_subj) or sent_subj).strip().lower()
            title = (offer_effective_title(off) or "").strip().lower()
            match = False
            if sent_needle and (
                needle == sent_needle
                or needle in sent_needle
                or sent_needle in needle
                or _offer_title_matches_needle(needle, sent_needle)
            ):
                match = True
            if not match and title and _offer_title_matches_needle(needle, title):
                match = True
            if not match and sent_subj and incoming_subject_binds_offer(subj_try, off):
                match = True
            if not match:
                continue
            rcpt = (log.recipient_email or "").strip()
            score = subject_match_score(subj_try, off) if subj_try else 0.0
            if contact and rcpt and (
                _canon_recipient(rcpt) == contact or seller_emails_equivalent(rcpt, contact)
            ):
                score += 200.0
            elif local_in and rcpt.split("@", 1)[0].lower() == local_in.lower():
                score += 120.0
            if best is None or score > best[0]:
                best = (score, off, "send_log_product_context")

    if best and best[1]:
        return best[1], best[2]
    return None, ""


async def _offer_for_mailing_log_row(
    session,
    user_id: int,
    log: MailingSendLog,
    *,
    contact_email: str = "",
) -> Offer | None:
    """
    Лот из строки журнала. Если offer_id устарел (перевалидация с delete Offer),
    ищем текущий лот по recipient + теме исходящего письма / OfferEmail.
    """
    from services.offer_matching import _load_offer
    from services.offer_storage import inbound_seller_offer_pool

    off = await _load_offer(
        session, user_id=int(user_id), offer_id=int(log.offer_id or 0)
    )
    if off:
        return off

    rcpt = _canon_recipient(contact_email or log.recipient_email or "")
    if not rcpt:
        return None
    pool = await inbound_seller_offer_pool(
        session, user_id=int(user_id), contact_email=rcpt, limit=24
    )
    sent_subj = (log.mail_subject or "").strip()

    if not pool and sent_subj:
        from services.offer_storage import (
            find_offer_by_product_title_in_subject,
            list_offers_for_validated_contact_email,
        )

        off_title = await find_offer_by_product_title_in_subject(
            session,
            user_id=int(user_id),
            subject=sent_subj,
            contact_email=rcpt,
            allow_outbound_subject=True,
        )
        if off_title:
            return off_title
        validated = await list_offers_for_validated_contact_email(
            session, user_id=int(user_id), contact_email=rcpt, limit=8
        )
        if len(validated) == 1:
            return validated[0]
        return None

    if not pool:
        return None
    if sent_subj:
        pick = _pick_offer_by_subject_in_list(pool, sent_subj)
        if pick:
            return pick
        bound = [o for o in pool if incoming_subject_binds_offer(sent_subj, o)]
        if len(bound) == 1:
            return bound[0]
        if bound:
            pick2 = _pick_offer_by_subject_in_list(bound, sent_subj)
            if pick2:
                return pick2

    if len(pool) == 1:
        return pool[0]
    return None


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
    """Строки журнала рассылки на этот email (лот подгружается по offer_id, без INNER JOIN)."""
    from services.offer_matching import _load_offer

    email = _canon_recipient(contact_email)
    if not email:
        return []

    raw = (contact_email or "").strip().lower()
    conds = [func.lower(MailingSendLog.recipient_email) == email]
    if raw and raw != email:
        conds.append(func.lower(MailingSendLog.recipient_email) == raw)

    async def _pair_logs(logs: list[MailingSendLog]) -> list[tuple[MailingSendLog, Offer]]:
        out: list[tuple[MailingSendLog, Offer]] = []
        seen: set[int] = set()
        for log in logs:
            lid = int(log.id)
            if lid in seen:
                continue
            seen.add(lid)
            off = await _offer_for_mailing_log_row(
                session, int(user_id), log, contact_email=email
            )
            if off:
                out.append((log, off))
        return out

    logs = (
        await session.execute(
            select(MailingSendLog)
            .where(MailingSendLog.user_id == int(user_id))
            .where(or_(*conds))
            .order_by(MailingSendLog.sent_at.desc(), MailingSendLog.id.desc())
            .limit(int(limit))
        )
    ).scalars().all()
    paired = await _pair_logs(list(logs))
    if paired:
        return paired

    broad_logs = (
        await session.execute(
            select(MailingSendLog)
            .where(MailingSendLog.user_id == int(user_id))
            .order_by(MailingSendLog.sent_at.desc(), MailingSendLog.id.desc())
            .limit(int(limit))
        )
    ).scalars().all()
    out: list[tuple[MailingSendLog, Offer]] = []
    seen_log: set[int] = set()
    for log in broad_logs:
        rcpt = log.recipient_email or ""
        if _canon_recipient(rcpt) != email and not seller_emails_equivalent(rcpt, contact_email):
            continue
        lid = int(log.id)
        if lid in seen_log:
            continue
        seen_log.add(lid)
        off = await _offer_for_mailing_log_row(
            session, int(user_id), log, contact_email=email
        )
        if off:
            out.append((log, off))
    if not out and email:
        return await _recover_mailing_log_rows(
            session, int(user_id), contact_email, limit=min(int(limit), 80)
        )
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
    subject: str = "",
) -> tuple[Offer | None, str, str, str]:
    """
    Входящее → лот и тема исходящего письма (/send).
    При нескольких лотах на один email сначала матч по теме Re:/Aw:.
    Returns: (offer, listing_url, outgoing_mail_subject, matched_by)
    """
    subj = (subject or "").strip()
    if subj and subject_is_informative(subj):
        off_subj, how_subj = await find_offer_from_mailing_log(
            session, int(user_id), contact_email, subj
        )
        if off_subj:
            link = (offer_effective_link(off_subj) or "").strip()
            out_subj = ""
            rows_subj = await _mailing_log_rows_for_recipient(
                session, int(user_id), contact_email, limit=400
            )
            oid = int(off_subj.id)
            for log, o in rows_subj:
                if int(o.id) == oid and (log.mail_subject or "").strip():
                    out_subj = (log.mail_subject or "").strip()
                    break
            return off_subj, link, out_subj, how_subj or "mailing_send_log"

    rows = await _mailing_log_rows_for_recipient(session, int(user_id), contact_email, limit=400)
    inbox = (inbox_email or "").strip().lower()

    def _pick(log: MailingSendLog, off: Offer) -> tuple[Offer | None, str, str, str]:
        link = (offer_effective_link(off) or "").strip()
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
    email = _canon_recipient(contact_email)
    if not email:
        return False
    raw = (contact_email or "").strip().lower()
    conds = [func.lower(MailingSendLog.recipient_email) == email]
    if raw and raw != email:
        conds.append(func.lower(MailingSendLog.recipient_email) == raw)
    hit = (
        await session.execute(
            select(MailingSendLog.id)
            .where(MailingSendLog.user_id == int(user_id))
            .where(or_(*conds))
            .limit(1)
        )
    ).scalar_one_or_none()
    if hit is not None:
        return True
    broad = (
        await session.execute(
            select(MailingSendLog.recipient_email)
            .where(MailingSendLog.user_id == int(user_id))
            .order_by(MailingSendLog.sent_at.desc())
            .limit(200)
        )
    ).scalars().all()
    return any(
        _canon_recipient(r or "") == email or seller_emails_equivalent(r or "", contact_email)
        for r in broad
    )


async def bindable_offers_for_mailing_recipient(
    session,
    user_id: int,
    contact_email: str,
) -> list[Offer]:
    """Уникальные лоты из журнала /send на этот email (с восстановлением offer_id)."""
    from services.offer_storage import offer_incoming_bindable

    rows = await _mailing_log_rows_for_recipient(
        session, int(user_id), contact_email, limit=400
    )
    if not rows:
        rows = await _recover_mailing_log_rows(
            session, int(user_id), contact_email, limit=80
        )
    seen: set[int] = set()
    ordered: list[Offer] = []
    for _log, off in rows:
        if not offer_incoming_bindable(off):
            continue
        oid = int(off.id)
        if oid in seen:
            continue
        seen.add(oid)
        ordered.append(off)
    if not ordered:
        for _log, off in rows:
            oid = int(off.id)
            if oid in seen:
                continue
            seen.add(oid)
            ordered.append(off)
    return ordered


async def resolve_primary_mailed_offer(
    session,
    user_id: int,
    contact_email: str,
    *,
    inbox_email: str = "",
    subject: str = "",
) -> Offer | None:
    """
    FI/poputka: 1 email — 1 лот из журнала; несколько следов — тема Re: / inbox / последний send.
    """
    offers = await bindable_offers_for_mailing_recipient(
        session, int(user_id), contact_email
    )
    if len(offers) == 1:
        return offers[0]
    if len(offers) > 1:
        if (subject or "").strip():
            off, _how = await find_offer_from_mailing_log(
                session, int(user_id), contact_email, subject or ""
            )
            if off:
                return off
        off, _link, _subj, _how = await resolve_inbound_from_send_log(
            session,
            user_id=int(user_id),
            contact_email=contact_email,
            inbox_email=(inbox_email or "").strip(),
            subject=subject or "",
        )
        if off:
            return off
        return offers[0]
    off, _link, _subj, _how = await resolve_inbound_from_send_log(
        session,
        user_id=int(user_id),
        contact_email=contact_email,
        inbox_email=(inbox_email or "").strip(),
        subject=subject or "",
    )
    if off:
        return off
    off2, _link2, _subj2, _how2 = await resolve_inbound_from_send_log(
        session,
        user_id=int(user_id),
        contact_email=contact_email,
        inbox_email="",
        subject=subject or "",
    )
    return off2


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


async def _recover_mailing_log_rows(
    session,
    user_id: int,
    contact_email: str,
    *,
    limit: int = 80,
) -> list[tuple[MailingSendLog, Offer]]:
    """Журнал есть, но offer_id в строках мёртв — восстановить лот по теме / OfferEmail."""
    email = _canon_recipient(contact_email)
    if not email:
        return []
    raw = (contact_email or "").strip().lower()
    conds = [func.lower(MailingSendLog.recipient_email) == email]
    if raw and raw != email:
        conds.append(func.lower(MailingSendLog.recipient_email) == raw)
    logs = (
        await session.execute(
            select(MailingSendLog)
            .where(MailingSendLog.user_id == int(user_id))
            .where(or_(*conds))
            .order_by(MailingSendLog.sent_at.desc(), MailingSendLog.id.desc())
            .limit(int(limit))
        )
    ).scalars().all()
    out: list[tuple[MailingSendLog, Offer]] = []
    seen: set[int] = set()
    for log in logs:
        lid = int(log.id)
        if lid in seen:
            continue
        seen.add(lid)
        off = await _offer_for_mailing_log_row(
            session, int(user_id), log, contact_email=email
        )
        if off:
            out.append((log, off))
    return out


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
    if not rows and (contact_email or "").strip():
        rows = await _recover_mailing_log_rows(
            session, int(user_id), contact_email, limit=80
        )

    subj_needle = product_title_from_subject(subject)
    in_norm = _norm_subject(subject).lower()
    in_product = (subj_needle or "").strip().lower()

    if in_product and rows:
        pool: list[Offer] = []
        seen_oid: set[int] = set()
        for _log, off in rows:
            oid = int(off.id)
            if oid in seen_oid:
                continue
            seen_oid.add(oid)
            pool.append(off)
        pick = _pick_offer_by_subject_in_list(pool, subject)
        if pick and _mailing_return_offer(pick):
            return pick, "mailing_early_subject_pick"

    if not rows:
        return None, ""

    for log, off in rows:
        sent_norm = _norm_subject(log.mail_subject or "").lower()
        if sent_norm and in_norm and sent_norm == in_norm:
            if _mailing_return_offer(off):
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
                if _mailing_return_offer(off):
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
            if _mailing_return_offer(off):
                return off, "mailing_subject_score"

        for log, off in rows:
            if subject_title_agrees(subject, off):
                if _mailing_return_offer(off):
                    return off, "mailing_subject"
            sent_subj = (log.mail_subject or "").strip()
            if sent_subj and subj_needle.lower() in sent_subj.lower():
                if _mailing_return_offer(off):
                    return off, "mailing_sent_subject"
            ot = (offer_effective_title(off) or "").strip()
            if ot and subj_needle.lower() in ot.lower():
                if _mailing_return_offer(off):
                    return off, "mailing_title"

    unique_ids = {int(off.id) for _log, off in rows}
    if len(unique_ids) == 1:
        _log, off = rows[0]
        if _mailing_return_offer(off):
            return off, "mailing_only_offer"
        return off, "mailing_only_recipient_relaxed"

    if subj_needle and subject_is_informative(subject):
        bound = [
            off
            for _log, off in rows[:48]
            if incoming_subject_binds_offer(subject, off)
        ]
        if bound:
            hit = _pick_offer_by_subject_in_list(bound, subject)
            if hit and _mailing_return_offer(hit):
                return hit, "mailing_subject_pick"

    off_latest = await find_latest_mailed_offer_for_recipient(
        session, int(user_id), contact_email
    )
    if off_latest:
        return off_latest, "mailing_latest_fallback"

    return None, ""
