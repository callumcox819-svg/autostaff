"""RFC822 reply threading (In-Reply-To / References) for inbox replies."""

from __future__ import annotations

from typing import Any


def normalize_rfc_message_id(raw: str | None) -> str | None:
    """Normalize Message-ID to angle-bracket form, or None if unusable."""
    s = (raw or "").strip()
    if not s:
        return None
    # Multiple IDs / junk → first token
    s = s.split()[0].strip()
    if not s:
        return None
    if s.startswith("<") and s.endswith(">") and len(s) > 2:
        return s
    s = s.strip("<>").strip()
    if not s or "@" not in s:
        return None
    return f"<{s}>"


def build_references_header(*message_ids: str | None) -> str | None:
    """Ordered unique Message-IDs for References (oldest → newest)."""
    out: list[str] = []
    seen: set[str] = set()
    for raw in message_ids:
        mid = normalize_rfc_message_id(raw)
        if not mid:
            continue
        key = mid.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(mid)
    if not out:
        return None
    return " ".join(out)


def threading_send_kwargs(
    inbound_rfc_message_id: str | None = None,
    *,
    outbound_rfc_message_id: str | None = None,
) -> dict[str, str]:
    """
    Kwargs for SMTP reply:
    - In-Reply-To = last inbound (seller), else our outbound
    - References = our cold/outbound Message-ID + inbound (same Gmail thread)
    """
    inbound = normalize_rfc_message_id(inbound_rfc_message_id)
    outbound = normalize_rfc_message_id(outbound_rfc_message_id)
    if not inbound and not outbound:
        return {}
    in_reply_to = inbound or outbound
    refs = build_references_header(outbound, inbound)
    kw: dict[str, str] = {"in_reply_to": in_reply_to}
    if refs:
        kw["references"] = refs
    return kw


async def resolve_inbound_rfc_message_id(
    session,
    *,
    acc_id: int | None = None,
    uid: str | None = None,
    mail_id: int | None = None,
    meta: dict[str, Any] | None = None,
) -> str | None:
    """Load seller Message-ID from FULL_META cache or IncomingMail row."""
    if meta:
        hit = normalize_rfc_message_id(str(meta.get("rfc_message_id") or ""))
        if hit:
            return hit

    from sqlalchemy import select

    from models import IncomingMail

    row = None
    try:
        if mail_id:
            row = (
                await session.execute(
                    select(IncomingMail).where(IncomingMail.id == int(mail_id)).limit(1)
                )
            ).scalars().first()
        elif acc_id and uid is not None:
            uid_s = str(uid or "").strip()
            if uid_s.startswith("S:"):
                uid_s = uid_s.split(":", 1)[1]
            uid_num = int(uid_s)
            row = (
                await session.execute(
                    select(IncomingMail)
                    .where(IncomingMail.account_id == int(acc_id))
                    .where(IncomingMail.imap_uid == int(uid_num))
                    .order_by(IncomingMail.id.desc())
                    .limit(1)
                )
            ).scalars().first()
    except Exception:
        return None

    if not row:
        return None
    return normalize_rfc_message_id(getattr(row, "rfc_message_id", None))


async def resolve_outbound_rfc_message_id(
    session,
    *,
    user_id: int,
    contact_email: str,
    inbox_email: str | None = None,
) -> str | None:
    """Message-ID последнего исходящего /send|тест на этого продавца (из mailing_send_log)."""
    from sqlalchemy import func, or_, select

    from models import MailingSendLog
    from services.offer_storage import normalize_incoming_seller_email

    contact = normalize_incoming_seller_email(contact_email) or (contact_email or "").strip().lower()
    if not contact or not user_id:
        return None

    inbox = (inbox_email or "").strip().lower()
    raw = (contact_email or "").strip().lower()
    conds = [func.lower(MailingSendLog.recipient_email) == contact]
    if raw and raw != contact:
        conds.append(func.lower(MailingSendLog.recipient_email) == raw)

    q = (
        select(MailingSendLog.rfc_message_id, MailingSendLog.from_account_email)
        .where(MailingSendLog.user_id == int(user_id))
        .where(or_(*conds))
        .where(MailingSendLog.rfc_message_id.isnot(None))
        .order_by(MailingSendLog.sent_at.desc(), MailingSendLog.id.desc())
        .limit(40)
    )
    rows = (await session.execute(q)).all()
    if not rows:
        return None

    if inbox:
        for mid, sent_from in rows:
            sf = (sent_from or "").strip().lower()
            if sf and sf == inbox:
                hit = normalize_rfc_message_id(mid)
                if hit:
                    return hit

    for mid, _sf in rows:
        hit = normalize_rfc_message_id(mid)
        if hit:
            return hit
    return None
