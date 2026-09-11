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
    parent_references: str | None = None,
) -> dict[str, str]:
    """
    Kwargs for SMTP reply:
    - In-Reply-To = last inbound (seller), else our outbound
    - References = cold outbound + parent chain + inbound (same Gmail thread)
    """
    inbound = normalize_rfc_message_id(inbound_rfc_message_id)
    outbound = normalize_rfc_message_id(outbound_rfc_message_id)
    parent_parts: list[str | None] = []
    if parent_references:
        parent_parts.extend((parent_references or "").split())
    if not inbound and not outbound and not any(parent_parts):
        return {}
    in_reply_to = inbound or outbound
    refs = build_references_header(outbound, *parent_parts, inbound)
    kw: dict[str, str] = {}
    if in_reply_to:
        kw["in_reply_to"] = in_reply_to
    if refs:
        kw["references"] = refs
    elif in_reply_to:
        kw["references"] = in_reply_to
    return kw


async def resolve_inbound_rfc_message_id(
    session,
    *,
    acc_id: int | None = None,
    uid: str | None = None,
    mail_id: int | None = None,
    meta: dict[str, Any] | None = None,
    from_email: str | None = None,
) -> str | None:
    """Load seller Message-ID from FULL_META cache or IncomingMail row."""
    if meta:
        hit = normalize_rfc_message_id(str(meta.get("rfc_message_id") or ""))
        if hit:
            return hit

    from sqlalchemy import func, select

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
            if ":" in uid_s:
                uid_s = uid_s.rsplit(":", 1)[-1]
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
        # Fallback: последнее входящее от этого продавца на ящик с Message-ID.
        if (not row or not getattr(row, "rfc_message_id", None)) and acc_id and from_email:
            from services.offer_storage import normalize_incoming_seller_email

            fe = normalize_incoming_seller_email(from_email) or (from_email or "").strip().lower()
            if fe:
                row = (
                    await session.execute(
                        select(IncomingMail)
                        .where(IncomingMail.account_id == int(acc_id))
                        .where(func.lower(IncomingMail.from_email) == fe)
                        .where(IncomingMail.rfc_message_id.isnot(None))
                        .order_by(IncomingMail.id.desc())
                        .limit(1)
                    )
                ).scalars().first()
    except Exception:
        return None

    if not row:
        return None
    return normalize_rfc_message_id(getattr(row, "rfc_message_id", None))


async def resolve_inbound_parent_references(
    session,
    *,
    mail_id: int | None = None,
    meta: dict[str, Any] | None = None,
) -> str | None:
    """References/In-Reply-To цепочка из письма продавца (FULL_META или БД)."""
    if meta:
        refs = (meta.get("rfc_references") or "").strip()
        irt = normalize_rfc_message_id(str(meta.get("rfc_in_reply_to") or ""))
        if refs or irt:
            return build_references_header(*(refs.split() if refs else []), irt)

    if not mail_id:
        return None
    try:
        from sqlalchemy import select

        from models import IncomingMail

        row = (
            await session.execute(
                select(IncomingMail).where(IncomingMail.id == int(mail_id)).limit(1)
            )
        ).scalars().first()
    except Exception:
        return None
    if not row:
        return None
    refs = (getattr(row, "rfc_references", None) or "").strip()
    irt = normalize_rfc_message_id(getattr(row, "rfc_in_reply_to", None))
    if not refs and not irt:
        return None
    return build_references_header(*(refs.split() if refs else []), irt)


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


async def load_dialog_thread_state(
    session,
    *,
    user_id: int,
    inbox_email: str,
    contact_email: str,
) -> tuple[str | None, str | None]:
    """(last_outbound_mid, accumulated_references) из ConversationLink."""
    from sqlalchemy import func, select

    from models import ConversationLink
    from services.offer_storage import normalize_incoming_seller_email

    inbox = (inbox_email or "").strip().lower()
    contact = normalize_incoming_seller_email(contact_email) or (contact_email or "").strip().lower()
    if not user_id or not inbox or not contact:
        return None, None
    row = (
        await session.execute(
            select(ConversationLink)
            .where(ConversationLink.user_id == int(user_id))
            .where(func.lower(ConversationLink.account_email) == inbox)
            .where(func.lower(ConversationLink.from_email) == contact)
            .limit(1)
        )
    ).scalars().first()
    if not row:
        return None, None
    last = normalize_rfc_message_id(getattr(row, "last_outbound_rfc_message_id", None))
    refs = (getattr(row, "thread_rfc_references", None) or "").strip() or None
    return last, refs


async def remember_dialog_outbound(
    session,
    *,
    user_id: int,
    inbox_email: str,
    contact_email: str,
    outbound_message_id: str | None,
    references_header: str | None = None,
) -> None:
    """После cold/пресета/текста/HTML — сохранить Message-ID в диалог (Gmail thread)."""
    from sqlalchemy import func, select

    from models import ConversationLink
    from services.offer_storage import normalize_incoming_seller_email

    mid = normalize_rfc_message_id(outbound_message_id)
    if not mid or not user_id:
        return
    inbox = (inbox_email or "").strip().lower()
    contact = normalize_incoming_seller_email(contact_email) or (contact_email or "").strip().lower()
    if not inbox or not contact:
        return

    row = (
        await session.execute(
            select(ConversationLink)
            .where(ConversationLink.user_id == int(user_id))
            .where(func.lower(ConversationLink.account_email) == inbox)
            .where(func.lower(ConversationLink.from_email) == contact)
            .limit(1)
        )
    ).scalars().first()
    chain = build_references_header(
        *((getattr(row, "thread_rfc_references", None) or "").split() if row else []),
        *((references_header or "").split() if references_header else []),
        mid,
    )
    if row is None:
        row = ConversationLink(
            user_id=int(user_id),
            account_email=inbox,
            from_email=contact,
            last_outbound_rfc_message_id=mid[:512],
            thread_rfc_references=(chain or mid)[:8000] if chain or mid else None,
        )
        session.add(row)
    else:
        row.last_outbound_rfc_message_id = mid[:512]
        if chain:
            row.thread_rfc_references = chain[:8000]
    await session.flush()


async def seed_dialog_after_cold_send(
    session,
    *,
    user_id: int,
    inbox_email: str,
    contact_email: str,
    outbound_message_id: str | None,
) -> None:
    """Сразу после /send|тест — якорь треда, чтобы пресет не ушёл отдельным письмом."""
    await remember_dialog_outbound(
        session,
        user_id=int(user_id),
        inbox_email=inbox_email,
        contact_email=contact_email,
        outbound_message_id=outbound_message_id,
        references_header=None,
    )


async def merge_dialog_references(
    session,
    *,
    user_id: int,
    inbox_email: str,
    contact_email: str,
    references_header: str | None,
) -> None:
    """Дописать References в диалог без смены last_outbound (входящее продавца)."""
    from sqlalchemy import func, select

    from models import ConversationLink
    from services.offer_storage import normalize_incoming_seller_email

    inbox = (inbox_email or "").strip().lower()
    contact = normalize_incoming_seller_email(contact_email) or (contact_email or "").strip().lower()
    chain = build_references_header(*((references_header or "").split() if references_header else []))
    if not user_id or not inbox or not contact or not chain:
        return

    row = (
        await session.execute(
            select(ConversationLink)
            .where(ConversationLink.user_id == int(user_id))
            .where(func.lower(ConversationLink.account_email) == inbox)
            .where(func.lower(ConversationLink.from_email) == contact)
            .limit(1)
        )
    ).scalars().first()
    if row is None:
        session.add(
            ConversationLink(
                user_id=int(user_id),
                account_email=inbox,
                from_email=contact,
                thread_rfc_references=chain[:8000],
            )
        )
    else:
        merged = build_references_header(
            *((getattr(row, "thread_rfc_references", None) or "").split()),
            *((chain or "").split()),
        )
        if merged:
            row.thread_rfc_references = merged[:8000]
    await session.flush()


async def absorb_inbound_thread_hints(
    session,
    *,
    user_id: int,
    inbox_email: str,
    contact_email: str,
    inbound_message_id: str | None,
    in_reply_to: str | None,
    references: str | None,
) -> None:
    """
    Ответ продавца знает реальный Message-ID нашей рассылки (In-Reply-To).
    Gmail иногда переписывает MID при SMTP — подменяем журнал на тот, что видит продавец.
    """
    from sqlalchemy import func, or_, select

    from models import MailingSendLog
    from services.offer_storage import normalize_incoming_seller_email

    contact = normalize_incoming_seller_email(contact_email) or (contact_email or "").strip().lower()
    inbox = (inbox_email or "").strip().lower()
    if not user_id or not contact:
        return

    irt = normalize_rfc_message_id(in_reply_to)
    inbound = normalize_rfc_message_id(inbound_message_id)
    ref_chain = build_references_header(
        *((references or "").split() if references else []),
        irt,
        inbound,
    )
    if inbox and ref_chain:
        await merge_dialog_references(
            session,
            user_id=int(user_id),
            inbox_email=inbox,
            contact_email=contact,
            references_header=ref_chain,
        )

    # Реальный MID холодного = In-Reply-To (или первый id в References).
    cold_hint = irt
    if not cold_hint and references:
        parts = [normalize_rfc_message_id(p) for p in (references or "").split()]
        parts = [p for p in parts if p]
        if parts:
            cold_hint = parts[0]
    if not cold_hint:
        return

    raw = (contact_email or "").strip().lower()
    conds = [func.lower(MailingSendLog.recipient_email) == contact]
    if raw and raw != contact:
        conds.append(func.lower(MailingSendLog.recipient_email) == raw)
    logs = (
        await session.execute(
            select(MailingSendLog)
            .where(MailingSendLog.user_id == int(user_id))
            .where(or_(*conds))
            .order_by(MailingSendLog.sent_at.desc(), MailingSendLog.id.desc())
            .limit(10)
        )
    ).scalars().all()
    matched = list(logs)
    if inbox:
        same_inbox = [
            r for r in logs if (r.from_account_email or "").strip().lower() == inbox
        ]
        if same_inbox:
            matched = same_inbox

    for log in matched:
        cur = normalize_rfc_message_id(getattr(log, "rfc_message_id", None))
        if cur and cur.lower() == cold_hint.lower():
            return
        log.rfc_message_id = cold_hint[:512]
        if inbox and not (log.from_account_email or "").strip():
            log.from_account_email = inbox[:255]
        await session.flush()
        return


def threading_send_kwargs_for_dialog(
    *,
    inbound_rfc_message_id: str | None = None,
    cold_outbound_rfc_message_id: str | None = None,
    last_our_outbound_rfc_message_id: str | None = None,
    parent_references: str | None = None,
    dialog_references: str | None = None,
) -> dict[str, str]:
    """
    Полная цепочка диалога:
    cold → наши прошлые ответы → References входящего → входящее.
    In-Reply-To = последнее входящее от продавца.
    """
    parent_parts: list[str | None] = []
    if dialog_references:
        parent_parts.extend((dialog_references or "").split())
    if parent_references:
        parent_parts.extend((parent_references or "").split())
    return threading_send_kwargs(
        inbound_rfc_message_id,
        outbound_rfc_message_id=cold_outbound_rfc_message_id,
        parent_references=build_references_header(
            last_our_outbound_rfc_message_id,
            *parent_parts,
        ),
    )
