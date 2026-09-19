"""RFC822 reply threading (In-Reply-To / References) for inbox replies."""

from __future__ import annotations

import re
from typing import Any

# Раньше считали любой <…@gmail.com> «синтетикой» и не ставили в In-Reply-To.
# На практике smtp.gmail.com часто ОСТАВЛЯЕТ клиентский Message-ID у получателя
# (см. .eml тест-мейлов) — тогда якорь должен быть именно он, а не id из Sent
# (<…@mail.gmail.com>), иначе Gmail открывает второй диалог.
_SYNTHETIC_LOCAL_MID_RE = re.compile(
    r"^<\d{10,}\.1\.\d{12,}@(?:gmail\.com|googlemail\.com)>$",
    re.I,
)


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


def is_synthetic_local_message_id(raw: str | None) -> bool:
    """Устарело: клиентский @gmail.com MID у получателя обычно есть — не отбрасываем.

    Оставлен для совместимости импортов/тестов; всегда False.
    """
    _ = raw
    return False


def is_client_smtp_message_id(raw: str | None) -> bool:
    """True если похоже на наш SMTP Message-ID (make_msgid / старый gmail-like)."""
    mid = normalize_rfc_message_id(raw)
    if not mid:
        return False
    if _SYNTHETIC_LOCAL_MID_RE.match(mid):
        return True
    host = mid[1:-1].rsplit("@", 1)[-1].lower()
    if host not in {"gmail.com", "googlemail.com"}:
        return False
    # python email.utils.make_msgid: <time.pid.rand@gmail.com>
    return bool(re.match(r"^<\d+\.\d+\.\d+@(?:gmail|googlemail)\.com>$", mid, re.I))


def usable_thread_message_id(raw: str | None) -> str | None:
    """Message-ID для In-Reply-To / References (включая клиентский @gmail.com)."""
    return normalize_rfc_message_id(raw)


def build_references_header(*message_ids: str | None) -> str | None:
    """Ordered unique Message-IDs for References (oldest → newest)."""
    out: list[str] = []
    seen: set[str] = set()
    for raw in message_ids:
        mid = usable_thread_message_id(raw)
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
    Kwargs for SMTP reply (как кнопка Reply в Gmail):
    - In-Reply-To = Message-ID первого письма рассылки у продавца в Inbox
      (часто наш клиентский <…@gmail.com>, не id из Sent @mail.gmail.com).
    - References = оригинал → цепочка → входящее продавца.
    """
    inbound = usable_thread_message_id(inbound_rfc_message_id)
    outbound = usable_thread_message_id(outbound_rfc_message_id)
    parent_parts: list[str | None] = []
    if parent_references:
        parent_parts.extend((parent_references or "").split())
    parent_ids = [usable_thread_message_id(p) for p in parent_parts]
    parent_ids = [p for p in parent_ids if p]
    if not inbound and not outbound and not parent_ids:
        return {}
    # Корень треда = оригинал рассылки (oldest), не последнее входящее.
    in_reply_to = outbound
    if not in_reply_to and parent_ids:
        in_reply_to = parent_ids[0]
    if not in_reply_to:
        in_reply_to = inbound
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
        hit = usable_thread_message_id(str(meta.get("rfc_message_id") or ""))
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
    return usable_thread_message_id(getattr(row, "rfc_message_id", None))


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
                hit = usable_thread_message_id(mid)
                if hit:
                    return hit

    for mid, _sf in rows:
        hit = usable_thread_message_id(mid)
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


async def refresh_cold_message_id_from_sent(
    session,
    *,
    user_id: int,
    account_email: str,
    account_password: str,
    contact_email: str,
    subject: str | None = None,
) -> str | None:
    """После /send Gmail переписывает MID — один раз читаем Sent и якорим тред."""
    current = await resolve_outbound_rfc_message_id(
        session,
        user_id=int(user_id),
        contact_email=contact_email,
        inbox_email=account_email,
    )
    if usable_thread_message_id(current):
        return current
    subj = (subject or "").strip()
    if not subj:
        from services.mailing_send_log import load_last_mailing_quote

        q = await load_last_mailing_quote(
            session,
            user_id=int(user_id),
            contact_email=contact_email,
            inbox_email=account_email,
        )
        subj = (q.get("subject") or "").strip()
    if not (account_email or "").strip() or not (account_password or "").strip() or not subj:
        return None
    try:
        from services.smtp_delivery_verify import fetch_real_sent_message_id

        real = await fetch_real_sent_message_id(
            account_email,
            account_password,
            subject=subj,
            to_email=contact_email,
            wait_sec=0.4,
        )
    except Exception:
        return None
    mid = usable_thread_message_id(real)
    if not mid:
        return None
    from sqlalchemy import func, or_, select

    from models import MailingSendLog
    from services.offer_storage import normalize_incoming_seller_email

    contact = normalize_incoming_seller_email(contact_email) or (contact_email or "").strip().lower()
    inbox = (account_email or "").strip().lower()
    conds = [func.lower(MailingSendLog.recipient_email) == contact]
    logs = (
        await session.execute(
            select(MailingSendLog)
            .where(MailingSendLog.user_id == int(user_id))
            .where(or_(*conds))
            .order_by(MailingSendLog.sent_at.desc(), MailingSendLog.id.desc())
            .limit(15)
        )
    ).scalars().all()
    for log in logs:
        sf = (log.from_account_email or "").strip().lower()
        if inbox and sf and sf != inbox:
            continue
        log.rfc_message_id = mid[:512]
        break
    await seed_dialog_after_cold_send(
        session,
        user_id=int(user_id),
        inbox_email=account_email,
        contact_email=contact_email,
        outbound_message_id=mid,
    )
    await session.flush()
    return mid


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


def thread_contact_aliases(*emails: str | None) -> list[str]:
    """Рассылка могла уйти на MP-ящик, ответ прийти с Gmail — оба адреса один диалог."""
    from services.offer_storage import normalize_incoming_seller_email

    out: list[str] = []
    seen: set[str] = set()
    for raw in emails:
        n = normalize_incoming_seller_email(raw) or (raw or "").strip().lower()
        if not n or "@" not in n or n in seen:
            continue
        seen.add(n)
        out.append(n)
    return out


async def alias_dialog_thread(
    session,
    *,
    user_id: int,
    inbox_email: str,
    source_contact: str,
    dest_contact: str,
    extra_references: str | None = None,
    cold_message_id: str | None = None,
) -> None:
    """Перенести якорь треда с адреса рассылки на From ответа продавца."""
    src = (source_contact or "").strip().lower()
    dst = (dest_contact or "").strip().lower()
    if not user_id or not src or not dst or src == dst:
        return
    last_src, refs_src = await load_dialog_thread_state(
        session,
        user_id=int(user_id),
        inbox_email=inbox_email,
        contact_email=src,
    )
    last_dst, refs_dst = await load_dialog_thread_state(
        session,
        user_id=int(user_id),
        inbox_email=inbox_email,
        contact_email=dst,
    )
    chain = build_references_header(
        *((refs_src or "").split() if refs_src else []),
        *((refs_dst or "").split() if refs_dst else []),
        *((extra_references or "").split() if extra_references else []),
        last_src,
        last_dst,
        cold_message_id,
    )
    anchor = normalize_rfc_message_id(cold_message_id) or last_src or last_dst
    if not anchor and not chain:
        return
    await remember_dialog_outbound(
        session,
        user_id=int(user_id),
        inbox_email=inbox_email,
        contact_email=dst,
        outbound_message_id=anchor,
        references_header=chain,
    )


async def absorb_inbound_thread_hints(
    session,
    *,
    user_id: int,
    inbox_email: str,
    contact_email: str,
    inbound_message_id: str | None,
    in_reply_to: str | None,
    references: str | None,
    mailing_recipient: str | None = None,
) -> None:
    """
    Ответ продавца знает реальный Message-ID нашей рассылки (In-Reply-To).
    Gmail иногда переписывает MID при SMTP — подменяем журнал на тот, что видит продавец.
    Если From ≠ адрес из /send — склеиваем оба контакта в один тред.
    """
    from sqlalchemy import func, or_, select

    from models import MailingSendLog

    aliases = thread_contact_aliases(contact_email, mailing_recipient)
    inbox = (inbox_email or "").strip().lower()
    if not user_id or not aliases:
        return

    irt = normalize_rfc_message_id(in_reply_to)
    inbound = normalize_rfc_message_id(inbound_message_id)
    ref_chain = build_references_header(
        *((references or "").split() if references else []),
        irt,
        inbound,
    )
    if inbox and ref_chain:
        for em in aliases:
            await merge_dialog_references(
                session,
                user_id=int(user_id),
                inbox_email=inbox,
                contact_email=em,
                references_header=ref_chain,
            )

    cold_hint = irt
    if not cold_hint and references:
        parts = [normalize_rfc_message_id(p) for p in (references or "").split()]
        parts = [p for p in parts if p]
        if parts:
            cold_hint = parts[0]

    inbound_ids = {
        (normalize_rfc_message_id(p) or "").lower()
        for p in (
            *((references or "").split() if references else []),
            irt,
        )
        if p
    }
    inbound_ids.discard("")

    if cold_hint:
        conds = [func.lower(MailingSendLog.recipient_email) == em for em in aliases]
        logs = (
            await session.execute(
                select(MailingSendLog)
                .where(MailingSendLog.user_id == int(user_id))
                .where(or_(*conds))
                .order_by(MailingSendLog.sent_at.desc(), MailingSendLog.id.desc())
                .limit(20)
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
                break
            if cur and cur.lower() in inbound_ids and cur.lower() != (inbound or "").lower():
                break
            log.rfc_message_id = cold_hint[:512]
            if inbox and not (log.from_account_email or "").strip():
                log.from_account_email = inbox[:255]
            await session.flush()
            break

    mailed = thread_contact_aliases(mailing_recipient)
    reply_from = thread_contact_aliases(contact_email)
    if inbox and mailed and reply_from and mailed[0] != reply_from[0]:
        await alias_dialog_thread(
            session,
            user_id=int(user_id),
            inbox_email=inbox,
            source_contact=mailed[0],
            dest_contact=reply_from[0],
            extra_references=ref_chain,
            cold_message_id=cold_hint,
        )


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
    In-Reply-To = оригинал рассылки (cold / первый id цепочки).
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
            *parent_parts,
            last_our_outbound_rfc_message_id,
        ),
    )


def format_gmail_style_reply_body(
    reply_text: str,
    *,
    parent_from_name: str | None = None,
    parent_from_email: str | None = None,
    parent_date_str: str | None = None,
    parent_body: str | None = None,
    root_body: str | None = None,
    root_from_name: str | None = None,
    root_from_email: str | None = None,
    root_date_str: str | None = None,
) -> str:
    """
    Пресет + цитата ответа продавца + цитата исходной рассылки (/send),
    если её нет во входящем письме.
    """
    text = (reply_text or "").rstrip()

    def _quote_block(
        body: str,
        *,
        from_name: str | None,
        from_email: str | None,
        date_str: str | None,
        fallback_who: str,
        limit: int,
    ) -> str:
        clean = (body or "").replace("\r\n", "\n").replace("\r", "\n").strip()
        if not clean:
            return ""
        if len(clean) > limit:
            clean = clean[:limit].rstrip() + "…"
        who = (from_name or "").strip() or (from_email or "").strip() or fallback_who
        when = (date_str or "").strip()
        attr = f"On {when} {who} wrote:" if when else f"On {who} wrote:"
        quoted = "\n".join(f"> {ln}" if ln else ">" for ln in clean.split("\n"))
        return f"{attr}\n{quoted}"

    parent_block = _quote_block(
        parent_body or "",
        from_name=parent_from_name,
        from_email=parent_from_email,
        date_str=parent_date_str,
        fallback_who="seller",
        limit=2500,
    )
    parts = [p for p in (text, parent_block) if p]
    out = "\n\n".join(parts)

    root = (root_body or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if root:
        marker = next((ln.strip() for ln in root.split("\n") if ln.strip()), "")[:48]
        if marker and marker not in (out or ""):
            root_block = _quote_block(
                root,
                from_name=root_from_name,
                from_email=root_from_email,
                date_str=root_date_str,
                fallback_who="me",
                limit=1800,
            )
            if root_block:
                nested = "\n".join(
                    f"> {ln}" if ln else ">" for ln in root_block.split("\n")
                )
                out = f"{out}\n>\n{nested}" if out else root_block
    return out
