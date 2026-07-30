"""Сохранение объявлений из JSON парсера в БД (все поля + email после валидации)."""

from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy import select as sa_select

from models import Offer, OfferEmail

_LINK_QS_RE = re.compile(r"\?.*$")
_RAW_EMAIL_RE = re.compile(r"[\w.+-]+@[\w.-]+\.[a-z]{2,}", re.I)


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
    """Цена для AQUA/карточки: колонка Offer.price, иначе item_price/price из raw_json, иначе default."""
    if not offer:
        return default
    p = str(getattr(offer, "price", None) or "").strip()
    if p:
        return p
    raw = parse_offer_raw(getattr(offer, "raw_json", None))
    v = _first_raw_str(raw, ("item_price", "price"))
    return v or default


def offer_effective_title(offer: Offer | None) -> str:
    """Название: Offer.title, иначе item_title/title из raw_json (VOID / валид. данные)."""
    if not offer:
        return ""
    t = str(getattr(offer, "title", None) or "").strip()
    if t:
        return t
    raw = parse_offer_raw(getattr(offer, "raw_json", None))
    t = _first_raw_str(
        raw,
        ("item_title", "title", "product_title", "ad_title", "offer_title", "name_title"),
    )
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
) -> Offer | None:
    """
    Aw:/Re: + название в теме → лот по title в БД (без email/log).
    Один однозначный match или лучший score среди кандидатов.
    """
    from services.offer_matching import (
        _pick_offer_by_subject_in_list,
        _pick_best_linked_by_subject,
        incoming_subject_binds_offer,
        is_seller_reply_subject,
        product_title_from_subject,
        subject_is_informative,
    )

    subj = (subject or "").strip()
    if not subject_is_informative(subj) or not is_seller_reply_subject(subj):
        return None

    needle = product_title_from_subject(subj).strip().lower()
    if len(needle) < 5:
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
        if not offer_effective_link(off):
            continue
        title = (offer_effective_title(off) or "").strip().lower()
        if not title or len(title) < 4:
            continue
        if title == needle:
            hits.append(off)
            continue
        if len(needle) >= 8 and needle in title:
            hits.append(off)
            continue
        if len(title) >= 8 and title in needle:
            hits.append(off)

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
    return None


async def list_offers_for_validated_contact_email(
    session,
    *,
    user_id: int,
    contact_email: str,
    limit: int = 80,
) -> list[Offer]:
    """Лоты, у которых в raw_json validated_emails есть этот продавец (после purge OfferEmail)."""
    from services.offer_matching import canon_seller_email

    want = canon_seller_email(contact_email)
    if not want:
        return []

    rows = (
        await session.execute(
            sa_select(Offer)
            .where(Offer.user_id == int(user_id))
            .order_by(Offer.id.desc())
            .limit(8000)
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
        for em in offer_contact_emails(off):
            if canon_seller_email(em) == want:
                seen.add(oid)
                out.append(off)
                break
        if len(out) >= int(limit):
            break
    return out


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
    return any(canon_seller_email(em) == want for em in offer_contact_emails(off))


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


async def offer_for_mailing_target(session, tgt: OfferEmail) -> Offer | None:
    """Offer для /send — всегда из БД по offer_id (не от detached relationship)."""
    oid = int(getattr(tgt, "offer_id", 0) or 0)
    if oid:
        off = await session.get(Offer, oid)
        if off is not None:
            return off
    return getattr(tgt, "offer", None)


def offer_effective_link(offer: Offer | None) -> str:
    """Ссылка ricardo.ch/tutti.ch: Offer.link, иначе item_link/link из raw_json."""
    if not offer:
        return ""
    link = str(getattr(offer, "link", None) or "").strip()
    if link:
        return link
    raw = parse_offer_raw(getattr(offer, "raw_json", None))
    return _first_raw_str(raw, ("item_link", "link", "url", "ad_url"))


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
    """Фото: Offer.photo, иначе item_photo/photo/image/img из raw_json."""
    if not offer:
        return ""
    p = str(getattr(offer, "photo", None) or "").strip()
    if p:
        return p
    raw = parse_offer_raw(getattr(offer, "raw_json", None))
    return _first_raw_str(raw, ("item_photo", "photo", "image", "img"))


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
            session.add(OfferEmail(offer_id=int(offer.id), email=em))
            email_rows_saved += 1
        payload["offer_id"] = int(offer.id)

    return offers_saved, offers_with_email, email_rows_saved, output_rows
