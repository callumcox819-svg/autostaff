"""Сохранение объявлений из JSON парсера в БД (все поля + email после валидации)."""

from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy import func, or_, select as sa_select

from models import Offer, OfferEmail


async def live_user_offer(session, *, user_id: int, offer_id: int | None) -> Offer | None:
    """Offer из БД для этого user. Удалённый / чужой id — None (не писать FK)."""
    if not offer_id:
        return None
    try:
        oid = int(offer_id)
    except (TypeError, ValueError):
        return None
    off = await session.get(Offer, oid)
    if not off:
        return None
    if int(getattr(off, "user_id", 0) or 0) != int(user_id):
        return None
    return off


_LINK_QS_RE = re.compile(r"\?.*$")
_RAW_EMAIL_RE = re.compile(r"[\w.+-]+@[\w.-]+\.[a-z]{2,}", re.I)

# Порядок полей как в VOID parser export
_VOID_EXPORT_FIELD_ORDER: tuple[str, ...] = (
    "item_title",
    "item_photo",
    "ads_number",
    "parser_views",
    "ads_number_bought",
    "ads_number_sold",
    "gender",
    "email",
    "person_reg_date",
    "item_price",
    "views",
    "rating",
    "created_date",
    "created_real_date",
    "phone",
    "item_desc",
    "location",
    "item_link",
    "person_link",
    "item_person_name",
)

_VOID_EXPORT_DUP_KEYS = frozenset({"title", "link", "price", "name", "person_name"})


def format_validated_export_item(item: dict[str, Any]) -> dict[str, Any]:
    """Один лот для validated_*.json — как VOID, без дублей title/link/price."""
    if not isinstance(item, dict):
        return {}
    out: dict[str, Any] = {}
    for key in _VOID_EXPORT_FIELD_ORDER:
        if key in item and item[key] is not None:
            out[key] = item[key]
    for key, val in item.items():
        if key in out or key in _VOID_EXPORT_DUP_KEYS:
            continue
        if key in ("validated_emails", "offer_id"):
            continue
        if val is not None and val != "":
            out[key] = val
    if item.get("validated_emails"):
        out["validated_emails"] = list(item["validated_emails"])
    oid = item.get("offer_id")
    if oid is not None:
        out["offer_id"] = int(oid)
    return out


def format_validated_export_document(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """{"items": [...]} с отступами как void-parser-result."""
    items = [format_validated_export_item(r) for r in (rows or []) if isinstance(r, dict)]
    return {"items": items}


def link_key(url: str) -> str:
    u = (url or "").strip().lower().rstrip("/")
    if not u:
        return ""
    u = _LINK_QS_RE.sub("", u)
    return u


def offer_fingerprint(item: dict[str, Any]) -> str:
    lk = link_key(str(item.get("item_link") or item.get("link") or ""))
    if lk:
        return f"link:{lk}"
    title = str(item.get("item_title") or item.get("title") or "").strip().lower()[:120]
    name = str(item.get("item_person_name") or item.get("person_name") or item.get("name") or "").strip().lower()[:80]
    return f"t:{title}|n:{name}"


def _title_from_item_dict(item: dict[str, Any]) -> str:
    """Название товара из VOID/парсера — разные ключи и вложенный void."""
    if not isinstance(item, dict):
        return ""
    for key in (
        "item_title",
        "title",
        "product_title",
        "ad_title",
        "offer_title",
        "name_title",
    ):
        v = item.get(key)
        if v is not None and str(v).strip():
            return str(v).strip()
    void = item.get("void")
    if isinstance(void, dict):
        t = _title_from_item_dict(void)
        if t:
            return t
    return ""


def fields_from_item(item: dict[str, Any]) -> dict[str, str]:
    return {
        "person_name": str(
            item.get("item_person_name")
            or item.get("person_name")
            or item.get("seller_name")
            or item.get("name")
            or ""
        ).strip(),
        "title": _title_from_item_dict(item),
        "price": str(item.get("item_price") or item.get("price") or "").strip(),
        "link": str(item.get("item_link") or item.get("link") or item.get("url") or "").strip(),
        "photo": str(
            item.get("item_photo") or item.get("photo") or item.get("image") or item.get("img") or ""
        ).strip(),
    }


def parse_offer_raw(raw_json: str | None) -> dict[str, Any]:
    if not raw_json:
        return {}
    try:
        data = json.loads(raw_json)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _first_raw_str(raw: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        v = str(raw.get(key) or "").strip()
        if v:
            return v
    return ""


def offer_effective_price(offer: Offer | None, *, default: str = "0") -> str:
    """Цена: item_price из raw_json (VOID), иначе колонка Offer.price."""
    if not offer:
        return default
    raw = parse_offer_raw(getattr(offer, "raw_json", None))
    v = _first_raw_str(raw, ("item_price", "price"))
    if v:
        return v
    p = str(getattr(offer, "price", None) or "").strip()
    return p or default


def offer_effective_title(offer: Offer | None) -> str:
    """Название: item_title из raw_json (VOID / validated), иначе Offer.title."""
    if not offer:
        return ""
    raw = parse_offer_raw(getattr(offer, "raw_json", None))
    t = _first_raw_str(
        raw,
        ("item_title", "title", "product_title", "ad_title", "offer_title", "name_title"),
    )
    if t:
        return t
    t = str(getattr(offer, "title", None) or "").strip()
    if t:
        return t
    void = raw.get("void")
    if isinstance(void, dict):
        nested = _title_from_item_dict(void)
        if nested:
            return nested
    return ""


def offer_validated_emails(offer: Offer | None) -> list[str]:
    raw = parse_offer_raw(getattr(offer, "raw_json", None) if offer else None)
    out: list[str] = []
    for key in ("validated_emails", "emails"):
        val = raw.get(key)
        if isinstance(val, list):
            for em in val:
                s = str(em or "").strip()
                if s and "@" in s:
                    out.append(s)
        elif isinstance(val, str) and "@" in val:
            out.append(val.strip())
    return out


def _emails_in_raw_value(val: Any, *, depth: int = 0) -> list[str]:
    if depth > 10:
        return []
    found: list[str] = []
    if isinstance(val, str):
        for m in _RAW_EMAIL_RE.findall(val):
            s = (m or "").strip()
            if s and "@" in s and not s.lower().startswith("http"):
                found.append(s)
    elif isinstance(val, dict):
        for k, v in val.items():
            if k in ("item_photo", "photo", "image", "img", "void"):
                if k != "void":
                    continue
            found.extend(_emails_in_raw_value(v, depth=depth + 1))
    elif isinstance(val, list):
        for x in val:
            found.extend(_emails_in_raw_value(x, depth=depth + 1))
    return found


def offer_contact_emails(offer: Offer | None) -> list[str]:
    """Email продавца: validated_emails + любые @ в raw_json (старые импорты)."""
    if not offer:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for em in offer_validated_emails(offer):
        s = (em or "").strip()
        if not s:
            continue
        key = s.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
    raw = parse_offer_raw(getattr(offer, "raw_json", None))
    for key in ("email", "seller_email", "contact_email", "validated_email", "item_email"):
        v = raw.get(key)
        if isinstance(v, str) and "@" in v:
            s = v.strip()
            if s.lower() not in seen:
                seen.add(s.lower())
                out.append(s)
    for em in _emails_in_raw_value(raw):
        if em.lower() not in seen:
            seen.add(em.lower())
            out.append(em)
    return out


def seller_hint_matches_offer(
    offer: Offer | None,
    *,
    contact_email: str = "",
    from_name: str = "",
) -> bool:
    """Связь лота с продавцом: email в JSON или имя."""
    if not offer:
        return False
    from services.offer_matching import canon_seller_email
    from services.seller_name import normalize_seller_name

    want = canon_seller_email(contact_email)
    if want:
        for em in offer_contact_emails(offer):
            if canon_seller_email(em) == want:
                return True
        local = want.split("@", 1)[0] if "@" in want else ""
        if len(local) >= 4:
            raw = parse_offer_raw(getattr(offer, "raw_json", None))
            pn = (
                (offer.person_name or "")
                or str(raw.get("item_person_name") or raw.get("person_name") or "")
            ).strip()
            if pn and local.lower() in normalize_seller_name(pn).lower().replace(" ", ""):
                return True

    fn = normalize_seller_name(from_name or "")
    if len(fn) >= 4:
        raw = parse_offer_raw(getattr(offer, "raw_json", None))
        pn = normalize_seller_name(
            (offer.person_name or "")
            or str(raw.get("item_person_name") or raw.get("person_name") or "")
        )
        if pn:
            fl = fn.lower()
            pl = pn.lower()
            if fl in pl or pl in fl or fl.split()[0] in pl:
                return True
    return False


async def list_offers_for_seller_contact_hints(
    session,
    *,
    user_id: int,
    contact_email: str,
    from_name: str = "",
    limit: int = 80,
) -> list[Offer]:
    """Лоты, где в JSON/имени есть этот продавец (рассылка до MailingSendLog / без validated_emails)."""
    rows = (
        await session.execute(
            sa_select(Offer)
            .where(Offer.user_id == int(user_id))
            .order_by(Offer.id.desc())
            .limit(5000)
        )
    ).scalars().all()

    seen: set[int] = set()
    out: list[Offer] = []
    for off in rows:
        oid = int(off.id)
        if oid in seen:
            continue
        if not offer_effective_link(off):
            continue
        if not seller_hint_matches_offer(
            off, contact_email=contact_email, from_name=from_name
        ):
            continue
        seen.add(oid)
        out.append(off)
        if len(out) >= int(limit):
            break
    return out


async def offer_has_seller_contact(
    session,
    *,
    user_id: int,
    offer_id: int,
    contact_email: str,
    from_name: str = "",
) -> bool:
    off = await session.get(Offer, int(offer_id))
    if not off or int(off.user_id) != int(user_id):
        return False
    return seller_hint_matches_offer(
        off, contact_email=contact_email, from_name=from_name
    )


async def find_offer_by_subject_and_seller_hint(
    session,
    *,
    user_id: int,
    contact_email: str,
    from_name: str,
    subject: str,
) -> Offer | None:
    """Тема Re: + привязка к продавцу (legacy, без журнала рассылки)."""
    from services.offer_matching import (
        _pick_offer_by_subject_in_list,
        incoming_subject_binds_offer,
        subject_is_informative,
    )

    subj = (subject or "").strip()
    if not subject_is_informative(subj):
        return None

    pool = await list_offers_for_seller_contact_hints(
        session,
        user_id=int(user_id),
        contact_email=contact_email,
        from_name=from_name,
        limit=120,
    )
    if pool:
        hit = _pick_offer_by_subject_in_list(pool, subj)
        if hit and incoming_subject_binds_offer(subj, hit):
            return hit
        for cand in pool:
            if incoming_subject_binds_offer(subj, cand):
                return cand
        if len(pool) == 1 and incoming_subject_binds_offer(subj, pool[0]):
            return pool[0]

    return None


async def find_offer_by_product_title_in_subject(
    session,
    *,
    user_id: int,
    subject: str,
    contact_email: str = "",
    allow_outbound_subject: bool = False,
) -> Offer | None:
    """
    Aw:/Re: + название в теме → лот по title в БД (без email/log).
    allow_outbound_subject: тема из журнала /send («Noch verfügbar? OFFER») без Re:.
    """
    from services.offer_matching import (
        _offer_title_matches_needle,
        _pick_offer_by_subject_in_list,
        _pick_best_linked_by_subject,
        incoming_subject_binds_offer,
        is_seller_reply_subject,
        offer_needle_is_too_generic,
        product_title_from_subject,
        subject_is_informative,
    )

    subj = (subject or "").strip()
    if not subject_is_informative(subj):
        return None
    if not allow_outbound_subject and not is_seller_reply_subject(subj):
        return None

    needle = product_title_from_subject(subj).strip().lower()
    if len(needle) < 4:
        return None

    if offer_needle_is_too_generic(needle):
        if (contact_email or "").strip():
            from services.mailing_send_log import (
                bindable_offers_for_mailing_recipient,
                list_offers_from_mailing_log,
            )

            mailed = await list_offers_from_mailing_log(
                session, int(user_id), contact_email, limit=24
            )
            if len(mailed) == 1:
                return mailed[0]
            bound = await bindable_offers_for_mailing_recipient(
                session, int(user_id), contact_email
            )
            if len(bound) == 1:
                return bound[0]
        return None

    scope: list[Offer] | None = None
    if (contact_email or "").strip():
        scope = await list_offers_for_validated_contact_email(
            session,
            user_id=int(user_id),
            contact_email=contact_email,
            limit=80,
        )
        if not scope:
            from services.mailing_send_log import list_offers_from_mailing_log

            scope = await list_offers_from_mailing_log(
                session, int(user_id), contact_email, limit=60
            )
        if not scope:
            scope = await list_offers_for_seller_contact_hints(
                session,
                user_id=int(user_id),
                contact_email=contact_email,
                from_name="",
                limit=80,
            )

    if scope:
        rows = scope
    else:
        rows = (
            await session.execute(
                sa_select(Offer)
                .where(Offer.user_id == int(user_id))
                .order_by(Offer.id.desc())
                .limit(8000)
            )
        ).scalars().all()

    hits: list[Offer] = []
    for off in rows:
        if not offer_incoming_bindable(off):
            continue
        title = (offer_effective_title(off) or "").strip().lower()
        if not title or len(title) < 4:
            continue
        if _offer_title_matches_needle(needle, title):
            hits.append(off)
            continue

    if not hits:
        return None
    if len(hits) == 1:
        return hits[0]

    pick = _pick_offer_by_subject_in_list(hits, subj)
    if pick:
        return pick

    best = _pick_best_linked_by_subject(
        hits, subject=subj, min_score=32.0, min_gap=4.0
    )
    if best and incoming_subject_binds_offer(subj, best):
        return best

    if (contact_email or "").strip():
        from services.mailing_send_log import offer_was_mailed_to

        mailed = [
            h
            for h in hits
            if await offer_was_mailed_to(
                session, int(user_id), int(h.id), contact_email
            )
        ]
        if len(mailed) == 1:
            return mailed[0]
        if mailed:
            pick2 = _pick_offer_by_subject_in_list(mailed, subj)
            if pick2 and incoming_subject_binds_offer(subj, pick2):
                return pick2
            if not offer_needle_is_too_generic(needle):
                return mailed[0]

    pick3 = _pick_offer_by_subject_in_list(hits, subj)
    if pick3 and incoming_subject_binds_offer(subj, pick3):
        return pick3
    if offer_needle_is_too_generic(needle):
        return None
    return hits[0] if len(hits) == 1 else None


def _seller_email_matches(stored: str, contact_email: str) -> bool:
    from services.offer_matching import canon_seller_email

    want = canon_seller_email(contact_email)
    if not want:
        return False
    s = (stored or "").strip()
    if not s or "@" not in s:
        return False
    return canon_seller_email(s) == want


async def load_user_validated_email_keys(session, user_id: int) -> set[str]:
    """Канонические email из OfferEmail — один адрес = один лот на user."""
    rows = (
        await session.execute(
            sa_select(OfferEmail.email)
            .join(Offer, Offer.id == OfferEmail.offer_id)
            .where(Offer.user_id == int(user_id))
        )
    ).all()
    out: set[str] = set()
    for (em,) in rows:
        c = normalize_incoming_seller_email(str(em or ""))
        if c:
            out.add(c)
    return out


async def strip_validated_email_from_other_offers(
    session,
    *,
    user_id: int,
    keep_offer_id: int,
    email: str,
) -> None:
    """Один validated email на одного user — только один offer_id."""
    from services.offer_matching import canon_seller_email

    want = canon_seller_email(email)
    if not want or not int(keep_offer_id or 0):
        return
    uid = int(user_id)
    keep = int(keep_offer_id)

    oe_rows = (
        await session.execute(
            sa_select(OfferEmail)
            .join(Offer, Offer.id == OfferEmail.offer_id)
            .where(Offer.user_id == uid)
            .where(OfferEmail.offer_id != keep)
        )
    ).scalars().all()
    for oe in oe_rows:
        if _seller_email_matches(oe.email or "", email):
            await session.delete(oe)

    others = (
        await session.execute(
            sa_select(Offer).where(Offer.user_id == uid).where(Offer.id != keep)
        )
    ).scalars().all()
    for off in others:
        raw = parse_offer_raw(getattr(off, "raw_json", None))
        lst = list(raw.get("validated_emails") or [])
        new_lst = [x for x in lst if not _seller_email_matches(str(x or ""), email)]
        if len(new_lst) != len(lst):
            raw["validated_emails"] = new_lst
            off.raw_json = json.dumps(raw, ensure_ascii=False)
        for key in ("email", "validated_email", "seller_email", "contact_email"):
            v = raw.get(key)
            if isinstance(v, str) and _seller_email_matches(v, email):
                raw[key] = ""
                off.raw_json = json.dumps(raw, ensure_ascii=False)


def normalize_incoming_seller_email(raw: str) -> str:
    """from_email IMAP → канон для поиска validated_emails / журнала рассылки."""
    from services.email_address import extract_email_address
    from services.offer_matching import canon_seller_email

    extracted = extract_email_address(raw)
    base = extracted or (raw or "").strip().lower()
    return canon_seller_email(base)


async def list_offers_for_validated_contact_email(
    session,
    *,
    user_id: int,
    contact_email: str,
    limit: int = 80,
) -> list[Offer]:
    """Лоты по OfferEmail (прямой поиск), validated_emails в raw_json, журнал рассылки."""
    from services.mailing_send_log import list_offers_from_mailing_log
    from services.offer_matching import canon_seller_email

    want = normalize_incoming_seller_email(contact_email)
    if not want:
        return []

    seen: set[int] = set()
    out: list[Offer] = []

    raw_in = (contact_email or "").strip().lower()
    email_conds = [func.lower(OfferEmail.email) == want]
    if raw_in and raw_in != want:
        email_conds.append(func.lower(OfferEmail.email) == raw_in)
    local_want = want.split("@", 1)[0] if "@" in want else ""
    domain_want = want.split("@", 1)[1] if "@" in want else ""
    if domain_want in ("gmail.com", "googlemail.com") and local_want:
        email_conds.append(
            func.replace(func.lower(OfferEmail.email), ".", "") == want.replace(".", "")
        )

    direct_rows = (
        await session.execute(
            sa_select(Offer)
            .join(OfferEmail, OfferEmail.offer_id == Offer.id)
            .where(Offer.user_id == int(user_id))
            .where(or_(*email_conds))
            .order_by(Offer.id.desc())
            .limit(max(int(limit), 40))
        )
    ).scalars().all()
    for off in direct_rows:
        oid = int(off.id)
        if oid in seen:
            continue
        seen.add(oid)
        out.append(off)
        if len(out) >= int(limit):
            return out

    try:
        from database import engine

        if engine.dialect.name == "postgresql":
            pat = f"%{want}%"
            id_rows = (
                await session.execute(
                    sa_select(Offer.id)
                    .where(Offer.user_id == int(user_id))
                    .where(Offer.raw_json.isnot(None))
                    .where(Offer.raw_json.ilike(pat))
                    .order_by(Offer.id.desc())
                    .limit(max(int(limit) * 3, 60))
                )
            ).scalars().all()
            for oid in id_rows:
                oid = int(oid)
                if oid in seen:
                    continue
                off = await session.get(Offer, oid)
                if not off or int(off.user_id) != int(user_id):
                    continue
                if not any(
                    canon_seller_email(em) == want for em in offer_contact_emails(off)
                ):
                    continue
                seen.add(oid)
                out.append(off)
                if len(out) >= int(limit):
                    return out
    except Exception:
        pass

    rows = (
        await session.execute(
            sa_select(Offer)
            .where(Offer.user_id == int(user_id))
            .order_by(Offer.id.desc())
            .limit(25000)
        )
    ).scalars().all()

    for off in rows:
        oid = int(off.id)
        if oid in seen:
            continue
        matched = False
        for em in offer_contact_emails(off):
            if canon_seller_email(em) == want:
                matched = True
                break
        if matched:
            seen.add(oid)
            out.append(off)
        if len(out) >= int(limit):
            break

    for off in await list_offers_from_mailing_log(
        session, int(user_id), contact_email, limit=max(40, int(limit))
    ):
        oid = int(off.id)
        if oid in seen:
            continue
        seen.add(oid)
        out.append(off)
        if len(out) >= int(limit):
            break
    return out


async def _offers_from_offer_email_rows(
    session,
    *,
    user_id: int,
    contact_email: str,
) -> list[Offer]:
    """Лоты с строкой OfferEmail (как после валидации) — без скана 25k."""
    want = normalize_incoming_seller_email(contact_email)
    if not want:
        return []
    raw_in = (contact_email or "").strip().lower()
    email_conds = [func.lower(OfferEmail.email) == want]
    if raw_in and raw_in != want:
        email_conds.append(func.lower(OfferEmail.email) == raw_in)
    local_want = want.split("@", 1)[0] if "@" in want else ""
    domain_want = want.split("@", 1)[1] if "@" in want else ""
    if domain_want in ("gmail.com", "googlemail.com") and local_want:
        email_conds.append(
            func.replace(func.lower(OfferEmail.email), ".", "") == want.replace(".", "")
        )

    rows = (
        await session.execute(
            sa_select(Offer)
            .join(OfferEmail, OfferEmail.offer_id == Offer.id)
            .where(Offer.user_id == int(user_id))
            .where(or_(*email_conds))
            .order_by(Offer.id.desc())
        )
    ).scalars().all()
    seen: set[int] = set()
    out: list[Offer] = []
    for off in rows:
        oid = int(off.id)
        if oid in seen:
            continue
        seen.add(oid)
        out.append(off)
    return out


async def inbound_seller_offer_pool(
    session,
    *,
    user_id: int,
    contact_email: str,
    limit: int = 12,
) -> list[Offer]:
    """Лоты продавца: OfferEmail, иначе только то, что уходило на этот email в /send."""
    from services.mailing_send_log import list_offers_from_mailing_log

    table_hits = await _offers_from_offer_email_rows(
        session, user_id=int(user_id), contact_email=contact_email
    )
    if table_hits:
        return table_hits[: max(int(limit), 1)]
    mailed = await list_offers_from_mailing_log(
        session, int(user_id), contact_email, limit=max(int(limit), 40)
    )
    if mailed:
        return mailed[: max(int(limit), 1)]
    validated = await list_offers_for_validated_contact_email(
        session,
        user_id=int(user_id),
        contact_email=contact_email,
        limit=max(int(limit), 40),
    )
    return validated[: max(int(limit), 1)]


def _pick_offer_from_inbound_subjects(
    pool: list[Offer],
    *,
    subject: str,
    body_text: str,
) -> Offer | None:
    from services.offer_matching import _pick_offer_by_subject_in_list, subject_is_informative
    from services.subject_offer import inbound_subject_is_weak_for_bind, subjects_for_inbound_resolve

    for subj_try in subjects_for_inbound_resolve(subject, body_text):
        if inbound_subject_is_weak_for_bind(subj_try):
            continue
        if not subject_is_informative(subj_try):
            continue
        pick = _pick_offer_by_subject_in_list(pool, subj_try)
        if pick:
            return pick
    return None


async def find_single_offer_for_seller_contact_email(
    session,
    *,
    user_id: int,
    contact_email: str,
    subject: str = "",
    body_text: str = "",
) -> Offer | None:
    """Один OfferEmail → один лот; несколько строк — OFFER из цитаты/темы среди этих лотов."""
    from services.mailing_send_log import offer_was_mailed_to, resolve_inbound_from_send_log

    subj = (subject or "").strip()

    table_hits = await _offers_from_offer_email_rows(
        session, user_id=int(user_id), contact_email=contact_email
    )
    if len(table_hits) == 1:
        return table_hits[0]

    pool = await inbound_seller_offer_pool(
        session, user_id=int(user_id), contact_email=contact_email, limit=12
    )
    if not pool:
        from services.mailing_send_log import find_offer_from_mailing_log, has_mailing_send_for_contact
        from services.subject_offer import subjects_for_inbound_resolve

        if await has_mailing_send_for_contact(session, int(user_id), contact_email):
            for subj_try in subjects_for_inbound_resolve(subj, body_text or ""):
                off_ml, _ = await find_offer_from_mailing_log(
                    session, int(user_id), contact_email, subj_try
                )
                if off_ml:
                    return off_ml
        off, _, _, _ = await resolve_inbound_from_send_log(
            session,
            user_id=int(user_id),
            contact_email=contact_email,
            subject=subj,
        )
        return off

    bindable = [o for o in pool if offer_incoming_bindable(o)]
    pool = bindable or pool

    if len(table_hits) > 1 or len(pool) > 1:
        pick = _pick_offer_from_inbound_subjects(
            pool, subject=subj, body_text=body_text or ""
        )
        if pick:
            return pick
        if len(table_hits) > 1:
            want = normalize_incoming_seller_email(contact_email)
            mailed = [
                off
                for off in pool
                if await offer_was_mailed_to(
                    session, int(user_id), int(off.id), want or contact_email
                )
            ]
            if len(mailed) == 1:
                return mailed[0]
            off, _, _, _ = await resolve_inbound_from_send_log(
                session,
                user_id=int(user_id),
                contact_email=contact_email,
                subject=subj,
            )
            if off and int(off.id) in {int(o.id) for o in pool}:
                return off

    if len(pool) == 1:
        return pool[0]

    off, _, _, _ = await resolve_inbound_from_send_log(
        session, user_id=int(user_id), contact_email=contact_email, subject=subj
    )
    if off and int(off.id) in {int(o.id) for o in pool}:
        return off
    fi = await find_offer_for_mailed_seller_reply(
        session,
        user_id=int(user_id),
        contact_email=contact_email,
        subject=subj,
        body_text=body_text or "",
    )
    return fi


async def find_offer_for_mailed_seller_reply(
    session,
    *,
    user_id: int,
    contact_email: str,
    subject: str = "",
    body_text: str = "",
    inbox_email: str = "",
) -> Offer | None:
    """
    FI / poputka88: входящее Re: от email, которому слали /send или в OfferEmail.
    Один лот в пуле — без угадывания по каталогу; несколько — по теме/OFFER.
    """
    from services.mailing_send_log import (
        find_offer_from_mailing_log,
        has_mailing_send_for_contact,
        resolve_inbound_from_send_log,
    )
    from services.offer_matching import (
        _pick_offer_by_subject_in_list,
        is_seller_reply_subject,
        subject_match_score,
    )
    from services.subject_offer import subjects_for_inbound_resolve

    subj = (subject or "").strip()
    contact = normalize_incoming_seller_email(contact_email) or (contact_email or "").strip().lower()
    if not contact:
        return None

    has_send = await has_mailing_send_for_contact(session, int(user_id), contact)
    if has_send:
        from services.mailing_send_log import resolve_fi_inbound_offer

        prim, _how_fi = await resolve_fi_inbound_offer(
            session,
            int(user_id),
            contact,
            subject=subj,
            body_text=body_text or "",
            inbox_email=(inbox_email or "").strip(),
        )
        if prim:
            return prim

    table = await _offers_from_offer_email_rows(
        session, user_id=int(user_id), contact_email=contact
    )
    if not has_send and not table and not is_seller_reply_subject(subj):
        return None

    if len(table) == 1:
        from services.incoming_lead_resolve import inbound_thread_binds_offer

        if inbound_thread_binds_offer(subj, body_text or "", table[0]):
            return table[0]
        return None

    pool = await inbound_seller_offer_pool(
        session, user_id=int(user_id), contact_email=contact, limit=20
    )
    bindable = [o for o in pool if offer_incoming_bindable(o)]
    pool = bindable or pool

    if len(pool) == 1:
        from services.incoming_lead_resolve import inbound_thread_binds_offer

        if inbound_thread_binds_offer(subj, body_text or "", pool[0]):
            return pool[0]
        off_t = await find_offer_by_product_title_in_subject(
            session,
            user_id=int(user_id),
            subject=subj,
            contact_email=contact,
        )
        if off_t:
            return off_t
        return None

    if pool:
        for subj_try in subjects_for_inbound_resolve(subj, body_text or ""):
            pick = _pick_offer_from_inbound_subjects(
                pool, subject=subj_try, body_text=body_text or ""
            )
            if pick:
                return pick
            pick = _pick_offer_by_subject_in_list(pool, subj_try)
            if pick:
                return pick
        if is_seller_reply_subject(subj):
            best: tuple[float, Offer] | None = None
            for o in pool:
                sc = subject_match_score(subj, o)
                if best is None or sc > best[0]:
                    best = (sc, o)
            if best and best[0] >= 28.0:
                return best[1]

    if has_send or table:
        off, _, _, _ = await resolve_inbound_from_send_log(
            session,
            user_id=int(user_id),
            contact_email=contact,
            subject=subj,
        )
        if off:
            return off
        for subj_try in subjects_for_inbound_resolve(subj, body_text or ""):
            off_ml, _ = await find_offer_from_mailing_log(
                session, int(user_id), contact, subj_try
            )
            if off_ml:
                return off_ml
        off_title = await find_offer_by_product_title_in_subject(
            session,
            user_id=int(user_id),
            subject=subj,
            contact_email=contact,
        )
        if off_title:
            return off_title
        off_out = await find_offer_by_product_title_in_subject(
            session,
            user_id=int(user_id),
            subject=subj,
            contact_email=contact,
            allow_outbound_subject=True,
        )
        if off_out:
            return off_out

    from services.offer_matching import subject_is_informative

    if is_seller_reply_subject(subj) or subject_is_informative(subj):
        off_any = await find_offer_by_product_title_in_subject(
            session,
            user_id=int(user_id),
            subject=subj,
            contact_email=contact,
        )
        if off_any:
            return off_any
    return None


async def offer_has_validated_email(
    session,
    *,
    user_id: int,
    offer_id: int,
    contact_email: str,
) -> bool:
    from services.offer_matching import canon_seller_email

    want = canon_seller_email(contact_email)
    if not want or not int(offer_id or 0):
        return False
    off = await session.get(Offer, int(offer_id))
    if not off or int(off.user_id) != int(user_id):
        return False
    if any(canon_seller_email(em) == want for em in offer_validated_emails(off)):
        return True
    oe_rows = (
        await session.execute(
            sa_select(OfferEmail).where(OfferEmail.offer_id == int(offer_id))
        )
    ).scalars().all()
    for oe in oe_rows:
        if _seller_email_matches(oe.email or "", contact_email):
            return True
    return False


async def append_contact_email_to_offer_raw(
    session,
    *,
    offer_id: int,
    email: str,
) -> None:
    """После /send сохранить email в raw_json (переживает purge OfferEmail)."""
    from services.offer_matching import canon_seller_email

    em = (email or "").strip()
    if not em or "@" not in em or not int(offer_id or 0):
        return
    off = await session.get(Offer, int(offer_id))
    if not off:
        return
    raw = parse_offer_raw(getattr(off, "raw_json", None))
    canon = canon_seller_email(em)
    existing = [canon_seller_email(x) for x in offer_contact_emails(off)]
    if canon in existing:
        return
    lst = list(raw.get("validated_emails") or [])
    lst.append(em)
    raw["validated_emails"] = lst
    off.raw_json = json.dumps(raw, ensure_ascii=False)
    uid = int(getattr(off, "user_id", 0) or 0)
    if uid:
        await strip_validated_email_from_other_offers(
            session,
            user_id=uid,
            keep_offer_id=int(offer_id),
            email=em,
        )


async def offer_for_mailing_target(session, tgt: OfferEmail) -> Offer | None:
    """Offer для /send — всегда из БД по offer_id (не от detached relationship)."""
    oid = int(getattr(tgt, "offer_id", 0) or 0)
    if oid:
        off = await session.get(Offer, oid)
        if off is not None:
            return off
    return getattr(tgt, "offer", None)


def offer_incoming_bindable(offer: Offer | None) -> bool:
    """Лот можно привязать к входящему без пустой колонки link (есть title/photo/link в raw_json)."""
    if not offer:
        return False
    return bool(
        (offer_effective_title(offer) or "").strip()
        or (offer_effective_link(offer) or "").strip()
        or (offer_effective_photo(offer) or "").strip()
    )


def offer_effective_link(offer: Offer | None) -> str:
    """Ссылка: item_link из raw_json, иначе Offer.link."""
    if not offer:
        return ""
    raw = parse_offer_raw(getattr(offer, "raw_json", None))
    from_raw = _first_raw_str(raw, ("item_link", "link", "url", "ad_url"))
    if from_raw:
        return from_raw
    return str(getattr(offer, "link", None) or "").strip()


def marketplace_service_label_from_link(link: str) -> str:
    u = (link or "").lower()
    if "ricardo.ch" in u:
        return "ricardo.ch"
    if "tutti.ch" in u:
        return "tutti.ch"
    return ""


def marketplace_service_label_from_offer(offer: Offer | None) -> str:
    return marketplace_service_label_from_link(offer_effective_link(offer))


async def find_offer_by_link(session, *, user_id: int, ad_url: str) -> Offer | None:
    """Offer по ссылке объявления (колонка link или item_link в raw_json)."""
    lk = link_key(ad_url)
    if not lk:
        return None
    rows = (
        await session.execute(
            sa_select(Offer)
            .where(Offer.user_id == int(user_id))
            .order_by(Offer.id.desc())
            .limit(800)
        )
    ).scalars().all()
    for off in rows:
        if link_key(offer_effective_link(off)) == lk:
            return off
    return None


def ensure_offer_link_column(offer: Offer | None, listing_url: str) -> None:
    """Дублируем item_link в Offer.link — find_offer_by_link и IMAP видят ссылку."""
    if not offer:
        return
    url = (listing_url or "").strip()
    if url and not str(getattr(offer, "link", None) or "").strip():
        offer.link = url


def offer_effective_photo(offer: Offer | None) -> str:
    """Фото: item_photo из raw_json (VOID), иначе Offer.photo."""
    if not offer:
        return ""
    raw = parse_offer_raw(getattr(offer, "raw_json", None))
    from_raw = _first_raw_str(raw, ("item_photo", "photo", "image", "img"))
    if from_raw:
        return from_raw
    return str(getattr(offer, "photo", None) or "").strip()


def index_validated_rows(validated: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Индекс результатов валидации email по ссылке объявления."""
    out: dict[str, dict[str, Any]] = {}
    for row in validated or []:
        raw = row.get("raw") if isinstance(row.get("raw"), dict) else row
        if not isinstance(raw, dict):
            continue
        key = offer_fingerprint(raw)
        if key:
            out[key] = row
        lk = link_key(str(raw.get("item_link") or raw.get("link") or ""))
        if lk:
            out[f"link:{lk}"] = row
    return out


def emails_from_validated_row(
    row: dict[str, Any] | None,
    norm_email,
    *,
    max_emails: int = 1,
) -> list[str]:
    """Не больше одной почты на лот — первая валидная из результата валидации."""
    if not row:
        return []
    limit = max(1, int(max_emails))
    picked: list[str] = []
    seen: set[str] = set()
    for key in ("emails", "validated_emails"):
        for e in row.get(key) or []:
            e2 = norm_email(str(e or ""))
            if not e2 or e2 in seen:
                continue
            seen.add(e2)
            picked.append(e2)
            if len(picked) >= limit:
                return picked
    return picked


def match_validated_row_for_item(
    item: dict[str, Any],
    vindex: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    """Строго: validated email только к тому VOID-лоту, чей item_link совпал."""
    lk = link_key(str(item.get("item_link") or item.get("link") or ""))
    if lk:
        row = vindex.get(f"link:{lk}")
        if row:
            return row
    return vindex.get(offer_fingerprint(item))


async def save_all_offers_from_import(
    session,
    *,
    user_id: int,
    items: list[dict[str, Any]],
    validated_rows: list[dict[str, Any]],
    norm_email,
    max_emails_per_offer: int = 1,
    skip_queue_emails: set[str] | None = None,
) -> tuple[int, int, int, list[dict[str, Any]]]:
    """
    Сохранить в БД каждый VOID-лот с валидной почтой (по item_link), полный raw_json.
    Returns: (offers_saved, offers_with_email, email_rows_saved, output_json_rows)
    """
    vindex = index_validated_rows(validated_rows)
    skip_q = {e.strip().lower() for e in (skip_queue_emails or set()) if e and str(e).strip()}
    reserved_emails = await load_user_validated_email_keys(session, int(user_id))
    for e in skip_q:
        c = normalize_incoming_seller_email(e) or e
        if c:
            reserved_emails.add(c)
    offers_saved = 0
    offers_with_email = 0
    email_rows_saved = 0
    output_rows: list[dict[str, Any]] = []
    offer_batch: list[tuple[Offer, list[str]]] = []
    seen_link_keys: set[str] = set()

    work: list[tuple[dict[str, Any], dict[str, Any] | None]] = []
    for row in validated_rows or []:
        raw = row.get("raw") if isinstance(row.get("raw"), dict) else row
        if not isinstance(raw, dict):
            continue
        picked = emails_from_validated_row(
            row, norm_email, max_emails=max_emails_per_offer
        )
        if not picked:
            continue
        lk = link_key(str(raw.get("item_link") or raw.get("link") or ""))
        if lk:
            if lk in seen_link_keys:
                continue
            seen_link_keys.add(lk)
        work.append((raw, row))

    if not work:
        for it in items:
            if not isinstance(it, dict):
                continue
            vrow = match_validated_row_for_item(it, vindex)
            picked = emails_from_validated_row(
                vrow, norm_email, max_emails=max_emails_per_offer
            )
            if not picked:
                continue
            lk = link_key(str(it.get("item_link") or it.get("link") or ""))
            if lk:
                if lk in seen_link_keys:
                    continue
                seen_link_keys.add(lk)
            work.append((it, vrow))

    for it, vrow in work:
        fields = fields_from_item(it)
        picked = emails_from_validated_row(
            vrow, norm_email, max_emails=max_emails_per_offer
        )
        if not picked:
            continue
        canon = normalize_incoming_seller_email(picked[0]) or picked[0].strip().lower()
        if canon in reserved_emails:
            continue

        payload = dict(it)
        payload.setdefault(
            "item_person_name",
            str(
                it.get("item_person_name")
                or it.get("person_name")
                or it.get("name")
                or ""
            ).strip(),
        )
        void_link = str(it.get("item_link") or it.get("link") or "").strip()
        if void_link:
            payload["item_link"] = void_link
        void_title = _title_from_item_dict(it)
        if void_title:
            payload["item_title"] = void_title
        if picked:
            payload["validated_emails"] = list(picked)

        offer = Offer(
            user_id=int(user_id),
            person_name=fields["person_name"] or None,
            title=fields["title"] or None,
            price=fields["price"] or None,
            link=fields["link"] or None,
            photo=fields["photo"] or None,
            raw_json=json.dumps(payload, ensure_ascii=False),
        )
        session.add(offer)
        if fields["link"]:
            ensure_offer_link_column(offer, fields["link"])
        offers_saved += 1

        queued = [em for em in picked[:max_emails_per_offer] if em.lower() not in skip_q]
        if queued:
            offers_with_email += 1
        offer_batch.append((offer, queued))
        output_rows.append(payload)

    await session.flush()

    for (offer, queued), payload in zip(offer_batch, output_rows):
        for em in queued:
            canon = normalize_incoming_seller_email(em) or em.strip().lower()
            if canon in reserved_emails:
                continue
            await strip_validated_email_from_other_offers(
                session,
                user_id=int(user_id),
                keep_offer_id=int(offer.id),
                email=em,
            )
            session.add(OfferEmail(offer_id=int(offer.id), email=em))
            reserved_emails.add(canon)
            email_rows_saved += 1
        payload["offer_id"] = int(offer.id)

    return offers_saved, offers_with_email, email_rows_saved, output_rows
