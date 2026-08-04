"""Поиск Offer по email, названию, цене, ссылке и полному JSON."""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any

from sqlalchemy import func, or_ as sa_or, select as sa_select

from models import ConversationLink, Offer, OfferEmail
from services.offer_storage import link_key, parse_offer_raw

_PRICE_NUM_RE = re.compile(r"(\d+(?:[.,]\d+)?)")


def _ratio(a: str, b: str) -> float:
    a = (a or "").strip().lower()
    b = (b or "").strip().lower()
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


_SUBJECT_EDGE_QUOTES_RE = re.compile(r'^["\'\s]+|["\'\s]+$', re.UNICODE)


def _strip_subject_edges(s: str) -> str:
    t = (s or "").strip()
    for _ in range(2):
        n = re.sub(r"^\[\s*", "", t)
        n = re.sub(r"\s*\]\s*$", "", n).strip()
        if n == t:
            break
        t = n
    for _ in range(3):
        n = _SUBJECT_EDGE_QUOTES_RE.sub("", t).strip()
        if n == t:
            break
        t = n
    t = re.sub(r'"\s*(?=[-–—])', " ", t)
    t = re.sub(r"\s{2,}", " ", t).strip()
    return t


def _norm_subject(subject: str) -> str:
    s = _strip_subject_edges((subject or "").strip())
    if not s:
        return ""
    for _ in range(5):
        n = re.sub(r"^(re|aw|fw|fwd|wg)\s*:\s*", "", s, flags=re.I).strip()
        if n == s:
            break
        s = n
    return s


def product_title_from_subject(subject: str) -> str:
    """Название товара (OFFER) из темы — те же пресеты, что /send и тест-маил."""
    from services.subject_offer import offer_title_from_inbound_subject

    extracted = offer_title_from_inbound_subject(subject)
    if extracted:
        norm_x = _norm_subject(extracted)
        if len(norm_x) >= 4:
            return norm_x
        if len(extracted) >= 4 and "[" not in extracted:
            return extracted

    subj = _norm_subject(subject)
    subj = re.sub(
        r"^(?:"
        r"interesse an|kaufinteresse|kurze frage zu|kurze anfrage zu|"
        r"anfrage zu|anfrage:|frage zu|pretenda per|"
        r"noch verfügbar\??|noch verfugbar\??|guten tag,?"
        r")\s*:?\s*",
        "",
        subj,
        flags=re.I,
    ).strip()

    _extract_patterns = (
        r"^ist\s+(.+?)\s+noch zu haben\??\s*$",
        r"^haben sie\s+(.+?)\s+noch\??\s*$",
        r"^noch nicht verkauft\?\s*(.+)\s*$",
        r"^guten tag,?\s*(.+?)\s+noch verfügbar\??\s*$",
        r"^guten tag,?\s*(.+?)\s+noch verfugbar\??\s*$",
        r"^guten tag,?\s*ist\s+(.+?)\s+noch verfügbar oder bereits verkauft\??\s*$",
        r"^guten tag,?\s*ist\s+(.+?)\s+noch verfugbar oder bereits verkauft\??\s*$",
        r"^(.+?)\s*[-–—]\s*noch da\??\s*$",
        r"^(.+?)\s*[-–—]\s*noch aktuell\??\s*$",
        r"^(.+?)\s*[-–—]\s*noch im verkauf\??\s*$",
        r"^(.+?)\s+noch verfügbar\??\s*$",
        r"^(.+?)\s+noch verfugbar\??\s*$",
    )
    for pat in _extract_patterns:
        m = re.match(pat, subj, flags=re.I)
        if m:
            extracted = _strip_subject_edges((m.group(1) or "").strip())
            if len(extracted) >= 4:
                subj = extracted
                break

    subj = _strip_subject_edges(subj)
    if len(subj) > 140:
        subj = subj[:137] + "…"
    return subj


def gag_link_title_from_mail(subject: str, offer: Offer | None = None) -> str:
    """Имя для GAG API — из Re:/Aw: темы, если лот в БД не совпадает с нитью письма."""
    from services.offer_storage import offer_effective_title

    subj_t = product_title_from_subject(subject)
    if offer and subj_t and subject_is_informative(subject):
        ot = (offer_effective_title(offer) or "").strip()
        if ot and not subject_title_agrees(subject, offer):
            if subject_match_score(subject, offer) < 40.0:
                return subj_t
    if offer:
        ot = (offer_effective_title(offer) or "").strip()
        if ot:
            if subj_t and subject_title_agrees(subject, offer):
                if len(subj_t) <= len(ot) + 8:
                    return subj_t
            if subj_t and (
                ot.lower() in subj_t.lower()
                or subj_t.lower() in ot.lower()
                or subject_match_score(subject, offer) >= 40.0
            ):
                return ot
            return ot
    if subj_t:
        return subj_t
    if offer:
        ot = (offer_effective_title(offer) or "").strip()
        if ot:
            return ot
    return (subject or "").strip() or "OFFER"


def _offer_title_matches_needle(needle: str, title: str) -> bool:
    n = (needle or "").strip().lower()
    t = (title or "").strip().lower()
    if len(n) < 4 or len(t) < 4:
        return False
    if offer_needle_is_too_generic(n):
        return n == t
    if n == t:
        return True
    if n in t or t in n:
        return True
    if len(n) >= 4 and re.search(rf"(?<![a-z0-9]){re.escape(n)}(?![a-z0-9])", t):
        return True
    return False


_GENERIC_PRODUCT_NEEDLES = frozenset(
    {
        "sofa",
        "couch",
        "lampe",
        "leuchte",
        "tisch",
        "stuhl",
        "sessel",
        "bett",
        "schrank",
        "regal",
        "velo",
        "fahrrad",
        "bike",
        "ebike",
        "auto",
        "pkw",
        "iphone",
        "handy",
        "telefon",
        "uhr",
        "tasche",
        "rucksack",
        "artikel",
        "inserat",
        "moebel",
        "möbel",
        "spiel",
        "buch",
        "buecher",
        "bücher",
        "jacke",
        "hose",
        "hemd",
        "schuhe",
        "schuh",
        "koffer",
        "werkzeug",
        "monitor",
        "fernseher",
        "tv",
        "pc",
        "laptop",
        "tablet",
        "kamera",
        "box",
    }
)


def offer_needle_is_too_generic(needle: str) -> bool:
    """
    Одно слово «Sofa», «Lampe» — не выбирать лот по fuzzy match по всей БД.
    Только журнал /send на этот email или полное название в теме.
    """
    n = re.sub(r"\s+", " ", (needle or "").strip().lower())
    if len(n) < 4:
        return True
    tokens = _distinctive_listing_tokens(n)
    if not tokens:
        return True
    if len(tokens) == 1:
        if tokens[0] in _GENERIC_PRODUCT_NEEDLES:
            return True
        if len(tokens[0]) <= 5:
            return True
    return False


def subject_title_agrees(subject: str, offer: Offer) -> bool:
    """Poputka-style: Re: <товар> совпадает с названием лота (не только год/стоп-слова)."""
    from services.offer_storage import offer_effective_title

    if subject_is_informative(subject):
        needle = product_title_from_subject(subject).lower()
    else:
        needle = _norm_subject(subject).lower()
    if len(needle) < 4:
        return False
    title = (offer_effective_title(offer) or "").strip().lower()
    if not title or len(title) < 4:
        return False
    if needle == title:
        return True
    if _offer_title_matches_needle(needle, title):
        return True
    if len(title) >= 8 and title in needle:
        return True
    if len(needle) >= 8 and needle in title:
        return True
    mt = _distinctive_listing_tokens(needle)
    tt = _distinctive_listing_tokens(title)
    if mt and tt:
        overlap = sum(1 for t in mt if t in tt)
        if overlap >= 2:
            return True
        if overlap >= 1 and len(mt) >= 2 and len(tt) >= 2:
            if _ratio(needle, title) >= 0.52:
                return True
    if _ratio(needle, title) >= 0.78:
        return True
    return False


def offer_display_title(
    subject: str,
    offer: Offer | None,
    *,
    mailing_bound: bool = False,
) -> str:
    """Товар в карточке: лот из рассылки/БД; тема Re: — только если совпадает с лотом."""
    from services.offer_storage import offer_effective_title

    ot = (offer_effective_title(offer) or "").strip() if offer else ""
    if offer and mailing_bound and ot:
        subj_t = product_title_from_subject(subject)
        if (
            subject_is_informative(subject)
            and subj_t
            and not subject_title_agrees(subject, offer)
        ):
            return subj_t
        return ot
    subj_t = product_title_from_subject(subject)
    if subject_is_informative(subject) and subj_t:
        if not offer or subject_title_agrees(subject, offer):
            return subj_t
        if not mailing_bound:
            return subj_t
    if not offer:
        return subj_t or (subject or "").strip()
    return ot or subj_t or (subject or "").strip()


# Минимум совпадения темы с лотом из conversation_links (старый диалог)
_CONV_AD_URL_MIN_SUBJECT_SCORE = 40.0
# Тема Re: и email продавца — лот только при явном совпадении названия
_SUBJECT_EMAIL_AGREE_MIN_SCORE = 52.0


def incoming_subject_binds_offer(subject: str, offer: Offer | None) -> bool:
    """Тема письма относится к этому лоту (не подставлять старую рассылку / conv)."""
    if not offer:
        return False
    if not subject_is_informative(subject):
        return True
    if subject_title_agrees(subject, offer):
        return True
    return subject_match_score(subject, offer) >= _SUBJECT_EMAIL_AGREE_MIN_SCORE


def _price_token(price: str) -> str:
    m = _PRICE_NUM_RE.search((price or "").replace(" ", ""))
    if not m:
        return ""
    return m.group(1).replace(",", ".")


def _canon_email(email: str) -> str:
    e = (email or "").strip().lower()
    if "@" not in e:
        return e
    local, domain = e.split("@", 1)
    local = local.strip()
    domain = domain.strip().lower()
    if "+" in local:
        local = local.split("+", 1)[0]
    if domain in ("googlemail.com", "gmail.com"):
        local = local.replace(".", "")
        domain = "gmail.com"
    return f"{local}@{domain}"


def canon_seller_email(email: str) -> str:
    return _canon_email(email)


_SUBJECT_STOP = frozenset(
    {
        "re",
        "aw",
        "fw",
        "fwd",
        "the",
        "und",
        "der",
        "die",
        "das",
        "for",
        "von",
        "from",
        "het",
        "de",
        "van",
        "voor",
        "your",
        "item",
        "artikel",
        "kurze",
        "frage",
        "anfrage",
        "interesse",
        "kaufinteresse",
        "verkauf",
        "verkauft",
        "verfügbar",
        "verfugbar",
        "aktuell",
        "haben",
        "noch",
        "nicht",
        "guten",
        "tag",
        "kauf",
    }
)

# Общие слова объявлений — не считаем «совпадением лота» (guter Zustand и т.п.).
_GENERIC_LISTING_TOKENS = frozenset(
    {
        "guter",
        "gute",
        "gut",
        "zustand",
        "sehr",
        "noch",
        "neu",
        "neuwertig",
        "gebraucht",
        "original",
        "ovp",
        "inkl",
        "inklusive",
        "beige",
        "beiges",
        "schwarz",
        "weiss",
        "weis",
        "grau",
        "rot",
        "blau",
        "grün",
        "gruen",
        "gross",
        "groß",
        "klein",
        "set",
        "top",
        "super",
        "wenig",
        "kaum",
        "absolut",
        "inklusive",
        "verkauf",
        "verkauft",
        "verfügbar",
        "verfugbar",
        "aktuell",
        "da",
        "haben",
        "habe",
        "nochmals",
    }
)

_YEAR_TOKEN_RE = re.compile(r"^20\d{2}$")


def _subject_tokens(subj: str) -> list[str]:
    parts = re.findall(r"[a-z0-9]{3,}", (subj or "").lower())
    return [p for p in parts if p not in _SUBJECT_STOP]


def _meaningful_subject_tokens(subj: str) -> list[str]:
    """Токены темы без Re:/годов — чтобы «2026» не склеивал разные лоты."""
    return [t for t in _subject_tokens(subj) if not _YEAR_TOKEN_RE.match(t)]


def _distinctive_listing_tokens(subj: str) -> list[str]:
    """Токены названия товара без «guter Zustand» и цветов."""
    return [
        t
        for t in _meaningful_subject_tokens(subj)
        if t not in _GENERIC_LISTING_TOKENS and len(t) >= 3
    ]


def distinctive_token_in_title(tok: str, title_l: str) -> bool:
    """Токен из темы совпадает с названием лота целым словом (не «nes» в «hemnes»)."""
    tok = (tok or "").strip().lower()
    title_l = (title_l or "").strip().lower()
    if not tok or not title_l:
        return False
    title_tokens = set(_meaningful_subject_tokens(title_l))
    if tok in title_tokens:
        return True
    if len(tok) >= 5:
        return bool(re.search(rf"(?<![a-z0-9]){re.escape(tok)}(?![a-z0-9])", title_l))
    return False


def score_offer(
    off: Offer,
    *,
    from_email: str = "",
    subject: str = "",
    from_name: str = "",
    body_text: str = "",
    email_hit: bool = False,
) -> float:
    score = 0.0
    subj = _norm_subject(subject)
    fn = (from_name or "").strip()
    body = (body_text or "").strip()
    body_l = body.lower()

    if email_hit:
        score += 120.0

    title = (off.title or "").strip()
    if subj and title:
        score += 90.0 * _ratio(subj, title)
        if subj.lower() in title.lower() or title.lower() in subj.lower():
            score += 15.0

    pname = (off.person_name or "").strip()
    if fn and pname:
        score += 45.0 * _ratio(fn, pname)
        if fn.lower() in pname.lower() or pname.lower() in fn.lower():
            score += 10.0

    price_tok = _price_token(off.price or "")
    if price_tok and price_tok in body.replace(" ", "").replace(",", "."):
        score += 35.0
    if price_tok and subj and price_tok in subj.replace(" ", ""):
        score += 20.0

    link = (off.link or "").strip()
    if link and link in body:
        score += 55.0
    lk = link_key(link)
    if lk and lk in body_l:
        score += 40.0

    raw = parse_offer_raw(getattr(off, "raw_json", None))
    if raw:
        loc = str(raw.get("location") or "").strip()
        if loc and len(loc) >= 3 and loc.lower() in body_l:
            score += 25.0
        raw_title = str(raw.get("item_title") or raw.get("title") or "").strip()
        if subj and raw_title:
            score += 30.0 * _ratio(subj, raw_title)
        raw_name = str(raw.get("item_person_name") or raw.get("person_name") or "").strip()
        if fn and raw_name:
            score += 25.0 * _ratio(fn, raw_name)
        score += _score_raw_json_fields(raw, subj=subj, fn=fn, body_l=body_l)

    return score


_RAW_SKIP_KEYS = frozenset(
    {"validated_emails", "offer_id", "item_photo", "photo", "image", "img", "email"}
)
_RAW_FIELD_WEIGHT: dict[str, float] = {
    "item_title": 28.0,
    "title": 28.0,
    "item_price": 22.0,
    "price": 22.0,
    "item_person_name": 20.0,
    "person_name": 20.0,
    "name": 18.0,
    "item_desc": 18.0,
    "location": 16.0,
    "item_link": 30.0,
    "link": 30.0,
    "person_link": 14.0,
    "phone": 25.0,
    "gender": 8.0,
}


def _score_raw_json_fields(
    raw: dict[str, Any],
    *,
    subj: str,
    fn: str,
    body_l: str,
) -> float:
    """Доп. баллы, если значения из парсера встречаются в письме."""
    hay = f"{subj} {fn} {body_l}".lower()
    extra = 0.0
    seen_vals: set[str] = set()
    for key, val in raw.items():
        if key in _RAW_SKIP_KEYS or val is None:
            continue
        if isinstance(val, (int, float)):
            s = str(val).strip()
        elif isinstance(val, str):
            s = val.strip()
        else:
            continue
        if len(s) < 3:
            continue
        sl = s.lower()
        if sl in seen_vals:
            continue
        seen_vals.add(sl)
        w = _RAW_FIELD_WEIGHT.get(str(key), 10.0)
        if sl in body_l or sl in hay:
            extra += w
            continue
        if key in ("item_link", "link", "person_link"):
            lk = link_key(s)
            if lk and lk in body_l:
                extra += w
    return extra


async def resolve_offer_for_incoming(
    session,
    *,
    user_id: int,
    from_email: str,
    subject: str,
    from_name: str,
    body_text: str = "",
) -> tuple[int | None, int | None]:
    """Найти Offer: сначала email, затем скоринг по всем полям."""
    fe_raw = (from_email or "").strip().lower()
    fe_can = _canon_email(fe_raw)

    email_pairs: list[tuple[OfferEmail, Offer]] = []
    q = (
        sa_select(OfferEmail, Offer)
        .join(Offer, Offer.id == OfferEmail.offer_id)
        .where(Offer.user_id == int(user_id))
    )
    conds = []
    if fe_raw:
        conds.append(func.lower(OfferEmail.email) == fe_raw)
    if fe_can and "@" in fe_can:
        local_can, domain_can = fe_can.split("@", 1)
        if domain_can in ("gmail.com", "googlemail.com"):
            conds.append(func.replace(func.lower(OfferEmail.email), ".", "") == fe_can.replace(".", ""))
        if local_can:
            conds.append(func.lower(OfferEmail.email).like(local_can + "@%"))
    if conds:
        email_pairs = (
            await session.execute(q.where(sa_or(*conds)).order_by(Offer.id.desc()).limit(80))
        ).all()

    if not email_pairs and fe_can:
        all_rows = (
            await session.execute(
                sa_select(OfferEmail, Offer)
                .join(Offer, Offer.id == OfferEmail.offer_id)
                .where(Offer.user_id == int(user_id))
                .order_by(Offer.id.desc())
                .limit(1200)
            )
        ).all()
        for oe, off in all_rows:
            if _canon_email((oe.email or "").strip().lower()) == fe_can:
                email_pairs.append((oe, off))
                break

    candidates: dict[int, tuple[Offer, OfferEmail | None, bool]] = {}
    for oe, off in email_pairs:
        candidates[int(off.id)] = (off, oe, True)

    # Всегда добавляем свежие офферы для матча по title/price/link/raw
    recent = (
        await session.execute(
            sa_select(Offer)
            .where(Offer.user_id == int(user_id))
            .order_by(Offer.id.desc())
            .limit(500)
        )
    ).scalars().all()
    for off in recent:
        oid = int(off.id)
        if oid not in candidates:
            candidates[oid] = (off, None, False)

    if not candidates:
        return None, None

    subj_strong = subject_is_informative(subject)

    # Re: … — сначала явное совпадение темы с лотом (poputka88), не «последний» email.
    if subj_strong and email_pairs:
        from services.offer_storage import offer_effective_link

        for oe, off in email_pairs:
            if not offer_effective_link(off):
                continue
            if subject_title_agrees(subject, off):
                return int(off.id), int(oe.id)

        best_sm = -1.0
        best_off: Offer | None = None
        best_oe: OfferEmail | None = None
        for oe, off in email_pairs:
            if not offer_effective_link(off):
                continue
            sm = subject_match_score(subject, off)
            if sm > best_sm:
                best_sm = sm
                best_off = off
                best_oe = oe
        if best_off and best_sm >= _SUBJECT_EMAIL_AGREE_MIN_SCORE:
            return int(best_off.id), int(best_oe.id) if best_oe else None

        if len(email_pairs) > 1:
            return None, None

    best_offer_id: int | None = None
    best_email_id: int | None = None
    best_score = -1.0

    for off, oe, email_hit in candidates.values():
        sc = score_offer(
            off,
            from_email=from_email,
            subject=subject,
            from_name=from_name,
            body_text=body_text,
            email_hit=email_hit,
        )
        if subj_strong and email_hit:
            sm = subject_match_score(subject, off)
            if sm < _SUBJECT_EMAIL_AGREE_MIN_SCORE:
                sc -= 200.0
            elif sm >= 70.0:
                sc += 40.0
        if sc > best_score:
            best_score = sc
            best_offer_id = int(off.id)
            best_email_id = int(oe.id) if oe else None

    min_score = 55.0 if subj_strong else (45.0 if not email_pairs else 35.0)
    if best_offer_id is not None and best_score >= min_score:
        return best_offer_id, best_email_id
    return None, None


def is_seller_reply_subject(subject: str) -> bool:
    """Ответ продавца на рассылку (Re:/Aw: в теме)."""
    s = _strip_subject_edges((subject or "").strip())
    return bool(re.match(r"^\s*(re|aw)\s*:", s, re.I))


def subject_is_informative(subject: str) -> bool:
    subj = _norm_subject(subject)
    if len(subj) >= 6 or len(_subject_tokens(subj)) >= 2:
        return True
    return is_seller_reply_subject(subject) and len(subj) >= 4


def subject_token_hits(subject: str, off: Offer) -> int:
    from services.offer_storage import offer_effective_title

    title_l = offer_effective_title(off).lower()
    if not title_l:
        return 0
    return sum(1 for tok in _subject_tokens(subject) if tok in title_l)


def subject_match_score(subject: str, off: Offer) -> float:
    """Сильный матч темы письма к названию оффера (для продавцов с несколькими лотами)."""
    from services.offer_storage import offer_effective_title

    subj = _norm_subject(subject)
    if len(subj) < 6:
        return 0.0
    title = offer_effective_title(off).lower()
    if not title:
        return 0.0

    score = 75.0 * _ratio(subj, title)
    if subj.lower() in title or title in subj.lower():
        score += 55.0

    subj_l = subj.lower()
    title_l = title.lower()
    tok_hits = 0
    for tok in _distinctive_listing_tokens(subj):
        if distinctive_token_in_title(tok, title_l):
            tok_hits += 1
            score += 24.0
    if tok_hits >= 2:
        score += 25.0 + tok_hits * 12.0
    if tok_hits >= 3:
        score += 40.0
    if tok_hits == 1:
        score = min(score, 38.0)
    if tok_hits == 0:
        score = min(score, 35.0)

    needle = product_title_from_subject(subject).lower()
    if len(needle) >= 8 and (needle in title or title in needle):
        score = max(score, 72.0)

    wants_set = any(w in subj_l for w in ("komplette", "complet", "complete", "set "))
    if wants_set:
        if any(w in title_l for w in ("komplette", "complet", "complete", "set")):
            score += 45.0
        if any(w in title_l for w in ("sticker", "valverde", "extra sticker")) and not any(
            w in title_l for w in ("komplette", "complet", "set")
        ):
            score -= 50.0

    return score


async def finalize_aqua_listing_context(
    session,
    *,
    user_id: int,
    listing_url: str,
    offer: Offer | None,
    subject: str = "",
) -> tuple[Offer | None, str, str, str | None, str | None]:
    """url + title + price + photo из Offer (raw_json VOID), без подмены лота по теме."""
    from services.offer_storage import (
        find_offer_by_link,
        offer_effective_link,
        offer_effective_photo,
        offer_effective_price,
        offer_effective_title,
    )

    if offer:
        url = (offer_effective_link(offer) or (listing_url or "").strip()).strip()
        title = (offer_effective_title(offer) or "").strip()
        if not title:
            title = gag_link_title_from_mail(subject, offer)
        price = offer_effective_price(offer, default="") or None
        image = offer_effective_photo(offer) or None
        return offer, url, title.strip(), price, image

    url = (listing_url or "").strip()
    off = await find_offer_by_link(session, user_id=int(user_id), ad_url=url) if url else None
    if off:
        offer = off
        url = (offer_effective_link(offer) or url).strip()
        title = (offer_effective_title(offer) or gag_link_title_from_mail(subject, offer)).strip()
        price = offer_effective_price(offer, default="") or None
        image = offer_effective_photo(offer) or None
        return offer, url, title, price, image

    title = gag_link_title_from_mail(subject, None)
    return None, url, title.strip(), None, None


_AQUA_SUBJECT_MIN_SCORE = 28.0
_AQUA_MULTI_SUBJECT_GAP = 12.0


def _aqua_offer_pair(
    subj: str,
    off: Offer | None,
    *,
    min_score: float | None,
) -> tuple[Offer, str] | None:
    from services.offer_storage import offer_effective_link

    if not off:
        return None
    link = offer_effective_link(off)
    if not link:
        return None
    if min_score is not None and subj and subject_is_informative(subj):
        if subject_match_score(subj, off) < min_score:
            return None
    return off, link


def _pick_best_linked_by_subject(
    offers: list[Offer],
    *,
    subject: str,
    min_score: float,
    min_gap: float = _AQUA_MULTI_SUBJECT_GAP,
) -> Offer | None:
    from services.offer_storage import offer_effective_link

    if not offers or not subject_is_informative(subject):
        return None

    ranked: list[tuple[Offer, float]] = []
    for off in offers:
        link = offer_effective_link(off)
        if not link:
            continue
        sc = subject_match_score(subject, off)
        if sc > 0:
            ranked.append((off, sc))
    if not ranked:
        return None

    ranked.sort(key=lambda x: x[1], reverse=True)
    best, best_sc = ranked[0]
    if best_sc < min_score:
        return None
    if len(ranked) == 1:
        return best
    _, second_sc = ranked[1]
    if best_sc - second_sc >= min_gap or best_sc >= min_score + 18:
        return best
    return None


async def find_offer_by_catalog_subject_match(
    session,
    *,
    user_id: int,
    subject: str,
) -> Offer | None:
    """
    Re: + уникальное название в теме → лот из каталога (legacy без email в JSON).
    Не подставляет чужой лот при близких score у двух офферов.
    """
    from services.offer_storage import offer_effective_link

    subj = (subject or "").strip()
    if not is_seller_reply_subject(subj):
        return None
    needle = product_title_from_subject(subj)
    if len(needle) < 6:
        return None

    rows = (
        await session.execute(
            sa_select(Offer)
            .where(Offer.user_id == int(user_id))
            .order_by(Offer.id.desc())
            .limit(5000)
        )
    ).scalars().all()
    linked = [o for o in rows if offer_effective_link(o)]
    if not linked:
        return None

    for subj_try in (subj, f"Re: {needle}" if needle else subj):
        hit = _pick_best_linked_by_subject(
            linked,
            subject=subj_try,
            min_score=38.0,
            min_gap=6.0,
        )
        if hit and incoming_subject_binds_offer(subj, hit):
            return hit
    return None


async def _load_offer(
    session,
    *,
    user_id: int,
    offer_id: int,
) -> Offer | None:
    return (
        await session.execute(
            sa_select(Offer)
            .where(Offer.id == int(offer_id))
            .where(Offer.user_id == int(user_id))
            .limit(1)
        )
    ).scalars().first()


def _pick_offer_by_subject_in_list(offers: list[Offer], subject: str) -> Offer | None:
    """Лучший лот из списка по теме Re: (substring / токены)."""
    from services.offer_storage import offer_effective_link, offer_effective_title

    needle = product_title_from_subject(subject) if subject_is_informative(subject) else _norm_subject(subject)
    if len(needle) < 4:
        return None
    nl = needle.lower()

    best: Offer | None = None
    best_len = 0
    for off in offers:
        title = (offer_effective_title(off) or "").strip()
        if not title or len(title) < 4:
            continue
        if not offer_effective_link(off):
            continue
        tl = title.lower()
        if _offer_title_matches_needle(needle, title):
            if len(title) > best_len:
                best = off
                best_len = len(title)
        elif subject_title_agrees(subject, off):
            if len(title) > best_len:
                best = off
                best_len = len(title)
    return best


async def find_offer_from_incoming_dialog(
    session,
    user_id: int,
    contact_email: str,
    *,
    inbox_email: str = "",
    subject: str = "",
    exclude_mail_id: int | None = None,
) -> tuple[Offer | None, str]:
    """
    Продолжение переписки: не прыгать на «последнюю рассылку» (Huawei),
    если уже был входящий от этого продавца с привязанным лотом (шорты).
    """
    from models import IncomingMail
    from services.offer_storage import offer_effective_link

    contact = canon_seller_email(contact_email)
    if not contact:
        return None, ""

    inbox = _canon_email(inbox_email) if inbox_email else ""
    norm_subj = _norm_subject(subject).lower()

    rows = (
        await session.execute(
            sa_select(IncomingMail)
            .where(IncomingMail.user_id == int(user_id))
            .where(func.lower(IncomingMail.from_email).in_([contact, (contact_email or "").strip().lower()]))
            .order_by(IncomingMail.id.desc())
            .limit(25)
        )
    ).scalars().all()

    for mail in rows:
        if exclude_mail_id and int(mail.id) == int(exclude_mail_id):
            continue
        if inbox:
            acc = _canon_email(getattr(mail, "account_email", "") or "")
            if acc and acc != inbox:
                continue
        oid = getattr(mail, "resolved_offer_id", None)
        if not oid:
            continue
        if not bool(getattr(mail, "mailing_bound", False)):
            continue
        subj_mail = (getattr(mail, "subject", "") or "").strip()
        prev_subj = _norm_subject(subj_mail).lower()
        needle_now = product_title_from_subject(subject or "").lower()
        prev_needle = product_title_from_subject(subj_mail).lower()
        if needle_now and prev_needle and len(needle_now) >= 5 and len(prev_needle) >= 5:
            if needle_now != prev_needle and needle_now not in prev_needle and prev_needle not in needle_now:
                continue
        elif norm_subj and prev_subj and norm_subj != prev_subj:
            if not (norm_subj in prev_subj or prev_subj in norm_subj):
                continue
        off = await _load_offer(session, user_id=int(user_id), offer_id=int(oid))
        if off and offer_effective_link(off):
            if subject_is_informative(subject) and not incoming_subject_binds_offer(subject, off):
                continue
            return off, "incoming_dialog"

    return None, ""


async def find_offer_by_incoming_subject(
    session,
    user_id: int,
    subject: str,
    from_email: str = "",
    *,
    mailed_only: bool = False,
) -> Offer | None:
    """Лид по теме Re: <товар> — сначала у этого продавца (poputka88)."""
    fe = (from_email or "").strip()
    if fe:
        if mailed_only:
            from services.mailing_send_log import list_offers_from_mailing_log

            seller_offers = await list_offers_from_mailing_log(
                session, int(user_id), fe, limit=80
            )
        else:
            seller_offers = await list_offers_for_seller_email(
                session, user_id=int(user_id), from_email=fe
            )
        hit = _pick_offer_by_subject_in_list(seller_offers, subject)
        if hit:
            return hit
        if mailed_only:
            return None

    if mailed_only:
        return None

    rows = (
        await session.execute(
            sa_select(Offer)
            .where(Offer.user_id == int(user_id))
            .order_by(Offer.id.desc())
            .limit(2500)
        )
    ).scalars().all()
    return _pick_offer_by_subject_in_list(list(rows), subject)


async def incoming_mail_product_snapshot(
    session,
    *,
    user_id: int,
    subject: str,
    from_email: str,
    offer: Offer | None,
) -> str:
    """Название товара для карточки/БД — не путаем Re: с чужим лотом по email."""
    off = offer
    if off is None and subject_is_informative(subject):
        off = await find_offer_by_incoming_subject(
            session, int(user_id), subject, from_email=from_email
        )
    return (offer_display_title(subject, off) or "").strip()


async def _load_conversation_link(
    session,
    *,
    user_id: int,
    inbox_email: str,
    contact_email: str,
) -> ConversationLink | None:
    inbox = _canon_email(inbox_email)
    contact = _canon_email(contact_email)
    if not inbox or not contact:
        return None
    return (
        await session.execute(
            sa_select(ConversationLink)
            .where(ConversationLink.user_id == int(user_id))
            .where(func.lower(ConversationLink.account_email) == inbox)
            .where(func.lower(ConversationLink.from_email) == contact)
            .limit(1)
        )
    ).scalars().first()


async def resolve_listing_for_incoming_mail(
    session,
    *,
    user_id: int,
    from_email: str,
    subject: str,
    from_name: str = "",
    body_text: str = "",
    resolved_offer_id: int | None = None,
    mail_ad_url: str | None = None,
    inbox_email: str | None = None,
    pinned_offer_id: int | None = None,
    conv_ad_url: str | None = None,
    mailed_only: bool = False,
) -> tuple[Offer | None, str]:
    """
    Единый выбор лота для карточки, IMAP и «Создать ссылку».
    mailed_only: только лоты из MailingSendLog (реально отправленные на этот email).
    """
    from services.mailing_send_log import list_offers_from_mailing_log, offer_was_mailed_to
    from services.offer_storage import ensure_offer_link_column, find_offer_by_link, offer_effective_link

    subj = _strip_subject_edges((subject or "").strip())
    fe = (from_email or "").strip()
    subj_strong = subject_is_informative(subj)

    async def _seller_offers() -> list[Offer]:
        if not fe:
            return []
        if mailed_only:
            from services.mailing_send_log import list_allowed_offers_for_incoming_contact

            return await list_allowed_offers_for_incoming_contact(
                session, int(user_id), fe, from_name=from_name, limit=80
            )
        return await list_offers_for_seller_email(
            session, user_id=int(user_id), from_email=fe
        )

    async def _mailed_ok(off: Offer | None) -> bool:
        if not off or not mailed_only or not fe:
            return True
        from services.mailing_send_log import offer_allowed_for_incoming_contact

        return await offer_allowed_for_incoming_contact(
            session, int(user_id), int(off.id), fe, from_name=from_name
        )

    if resolved_offer_id and subj_strong:
        off_stale = await _load_offer(
            session, user_id=int(user_id), offer_id=int(resolved_offer_id)
        )
        if off_stale and not subject_title_agrees(subj, off_stale):
            resolved_offer_id = None

    if not (pinned_offer_id or conv_ad_url) and (inbox_email or "").strip() and fe:
        conv = await _load_conversation_link(
            session,
            user_id=int(user_id),
            inbox_email=inbox_email or "",
            contact_email=fe,
        )
        if conv:
            if pinned_offer_id is None and getattr(conv, "pinned_offer_id", None):
                pinned_offer_id = int(conv.pinned_offer_id)
            if not conv_ad_url:
                conv_ad_url = (conv.ad_url or "").strip() or None

    if subj_strong and pinned_offer_id:
        off_pin = await _load_offer(
            session, user_id=int(user_id), offer_id=int(pinned_offer_id)
        )
        if off_pin and not subject_title_agrees(subj, off_pin):
            pinned_offer_id = None

    if subj_strong and (conv_ad_url or "").strip():
        off_conv = await find_offer_by_link(
            session, user_id=int(user_id), ad_url=(conv_ad_url or "").strip()
        )
        if off_conv and not subject_title_agrees(subj, off_conv):
            conv_ad_url = None

    def _ret(off: Offer | None) -> tuple[Offer | None, str]:
        if not off:
            return None, ""
        link = (offer_effective_link(off) or "").strip()
        if link:
            ensure_offer_link_column(off, link)
        return off, link

    if subj_strong and fe:
        seller_first = await _seller_offers()
        off_seller = _pick_offer_by_subject_in_list(seller_first, subj)
        if off_seller and await _mailed_ok(off_seller):
            return _ret(off_seller)

    if subj_strong:
        off_subj = await find_offer_by_incoming_subject(
            session, int(user_id), subj, from_email=fe, mailed_only=mailed_only
        )
        if off_subj and await _mailed_ok(off_subj):
            return _ret(off_subj)

    if subj_strong and not mailed_only:
        recent = (
            await session.execute(
                sa_select(Offer)
                .where(Offer.user_id == int(user_id))
                .order_by(Offer.id.desc())
                .limit(800)
            )
        ).scalars().all()
        off = _pick_best_linked_by_subject(
            list(recent),
            subject=subj,
            min_score=34.0,
            min_gap=16.0,
        )
        if off:
            return _ret(off)

        off = await resolve_best_offer_by_subject_global(
            session,
            user_id=int(user_id),
            subject=subj,
            from_name=from_name,
            body_text=body_text,
        )
        pair = _aqua_offer_pair(subj, off, min_score=_AQUA_SUBJECT_MIN_SCORE)
        if pair:
            return pair

        seller_offers = await _seller_offers()
        multi = len(seller_offers) > 1
        off = _pick_best_linked_by_subject(
            seller_offers,
            subject=subj,
            min_score=_SUBJECT_EMAIL_AGREE_MIN_SCORE,
            min_gap=14.0 if multi else 8.0,
        )
        if off:
            return _ret(off)

        off = _pick_best_offer_by_subject_scores(
            seller_offers,
            subject=subj,
            from_name=from_name,
            body_text=body_text,
            min_score=50.0 if multi else _SUBJECT_EMAIL_AGREE_MIN_SCORE,
        )
        pair = _aqua_offer_pair(subj, off, min_score=_SUBJECT_EMAIL_AGREE_MIN_SCORE)
        if pair:
            return pair

    murl = (mail_ad_url or "").strip()
    if murl:
        off = await find_offer_by_link(session, user_id=int(user_id), ad_url=murl)
        min_sc = _CONV_AD_URL_MIN_SUBJECT_SCORE if subject_is_informative(subj) else None
        pair = _aqua_offer_pair(subj, off, min_score=min_sc)
        if pair and await _mailed_ok(off):
            return pair
        if off and not subject_is_informative(subj) and await _mailed_ok(off):
            link = offer_effective_link(off) or murl
            if link:
                ensure_offer_link_column(off, link)
                return off, link

    if resolved_offer_id:
        off = await _load_offer(session, user_id=int(user_id), offer_id=int(resolved_offer_id))
        min_sc = _SUBJECT_EMAIL_AGREE_MIN_SCORE if subj_strong else None
        pair = _aqua_offer_pair(subj, off, min_score=min_sc)
        if pair and await _mailed_ok(off):
            return pair

    if pinned_offer_id:
        off = await _load_offer(session, user_id=int(user_id), offer_id=int(pinned_offer_id))
        min_sc = _SUBJECT_EMAIL_AGREE_MIN_SCORE if subj_strong else None
        pair = _aqua_offer_pair(subj, off, min_score=min_sc)
        if pair and await _mailed_ok(off):
            return pair

    curl = (conv_ad_url or "").strip()
    if curl:
        off = await find_offer_by_link(session, user_id=int(user_id), ad_url=curl)
        if off and await _mailed_ok(off):
            if not subj_strong:
                return _ret(off)
            if subject_title_agrees(subj, off):
                return _ret(off)

    if not mailed_only:
        oid, _ = await resolve_offer_for_incoming(
            session,
            user_id=int(user_id),
            from_email=fe,
            subject=subj,
            from_name=from_name,
            body_text=body_text,
        )
        if oid:
            off = await _load_offer(session, user_id=int(user_id), offer_id=int(oid))
            pair = _aqua_offer_pair(
                subj,
                off,
                min_score=_AQUA_SUBJECT_MIN_SCORE if subject_is_informative(subj) else None,
            )
            if pair:
                return pair

    seller_offers = await _seller_offers()
    if subject_is_informative(subj) and len(seller_offers) > 1:
        off = _pick_best_linked_by_subject(
            seller_offers,
            subject=subj,
            min_score=_SUBJECT_EMAIL_AGREE_MIN_SCORE,
            min_gap=10.0,
        )
        if off and await _mailed_ok(off):
            return _ret(off)
        for cand in seller_offers:
            if subject_title_agrees(subj, cand) and await _mailed_ok(cand):
                return _ret(cand)
        return None, ""

    if not subject_is_informative(subj):
        if len(seller_offers) == 1:
            only = seller_offers[0]
            if await _mailed_ok(only):
                return _ret(only)

    return None, ""


async def resolve_offer_for_aqua_link(
    session,
    *,
    user_id: int,
    from_email: str,
    subject: str,
    from_name: str = "",
    body_text: str = "",
    resolved_offer_id: int | None = None,
    mail_ad_url: str | None = None,
    inbox_email: str | None = None,
    mailing_bound: bool = False,
) -> tuple[Offer | None, str]:
    """Кнопка «Создать ссылку» — тот же резолвер, что IMAP-карточка."""
    from services.incoming_lead_resolve import resolve_offer_for_incoming_lead
    from services.offer_storage import offer_effective_link, normalize_incoming_seller_email

    contact = normalize_incoming_seller_email(from_email) or (from_email or "").strip().lower()
    off, url, _how, _snap = await resolve_offer_for_incoming_lead(
        session,
        user_id=int(user_id),
        contact_email=contact,
        subject=(subject or "").strip(),
        from_name=(from_name or "").strip(),
        body_text=(body_text or "").strip(),
        resolved_offer_id=resolved_offer_id,
        mail_ad_url=mail_ad_url,
        inbox_email=inbox_email,
        mailing_bound=mailing_bound,
    )
    url = (url or "").strip() or ((offer_effective_link(off) or "").strip() if off else "")
    return off, url


async def list_offers_for_seller_email(
    session,
    *,
    user_id: int,
    from_email: str,
) -> list[Offer]:
    fe_raw = (from_email or "").strip().lower()
    fe_can = _canon_email(fe_raw)
    if not fe_can:
        return []

    conds = []
    if fe_raw:
        conds.append(func.lower(OfferEmail.email) == fe_raw)
    if fe_can and "@" in fe_can:
        conds.append(func.lower(OfferEmail.email) == fe_can)
        local_can, domain_can = fe_can.split("@", 1)
        if domain_can in ("gmail.com", "googlemail.com"):
            conds.append(
                func.replace(func.lower(OfferEmail.email), ".", "") == fe_can.replace(".", "")
            )

    if not conds:
        return []

    rows = (
        await session.execute(
            sa_select(Offer)
            .join(OfferEmail, OfferEmail.offer_id == Offer.id)
            .where(Offer.user_id == int(user_id))
            .where(sa_or(*conds))
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
    if out:
        return out

    from services.mailing_send_log import list_offers_from_mailing_log

    return await list_offers_from_mailing_log(
        session, int(user_id), from_email, limit=80
    )


def _pick_best_offer_by_subject_scores(
    offers: list[Offer],
    *,
    subject: str,
    from_name: str = "",
    body_text: str = "",
    min_score: float,
) -> Offer | None:
    if not offers or not subject_is_informative(subject):
        return None

    best: Offer | None = None
    best_sc = -1.0
    for off in offers:
        sc = subject_match_score(subject, off)
        sc += (
            score_offer(
                off,
                subject=subject,
                from_name=from_name,
                body_text=body_text,
                email_hit=False,
            )
            * 0.3
        )
        if sc > best_sc:
            best_sc = sc
            best = off

    if best is None:
        return None
    if best_sc >= min_score:
        return best
    if subject_token_hits(subject, best) >= 3 and best_sc >= 48.0:
        return best
    return None


async def resolve_best_offer_by_subject(
    session,
    *,
    user_id: int,
    from_email: str,
    subject: str,
    from_name: str = "",
    body_text: str = "",
) -> Offer | None:
    offers = await list_offers_for_seller_email(session, user_id=int(user_id), from_email=from_email)
    if not offers:
        return None

    multi = len(offers) > 1
    return _pick_best_offer_by_subject_scores(
        offers,
        subject=subject,
        from_name=from_name,
        body_text=body_text,
        min_score=58.0 if multi else 42.0,
    )


async def resolve_best_offer_by_subject_global(
    session,
    *,
    user_id: int,
    subject: str,
    from_name: str = "",
    body_text: str = "",
) -> Offer | None:
    """Если email привязан к другому лоту — ищем оффер по теме среди всех объявлений пользователя."""
    if not subject_is_informative(subject):
        return None

    recent = (
        await session.execute(
            sa_select(Offer)
            .where(Offer.user_id == int(user_id))
            .order_by(Offer.id.desc())
            .limit(800)
        )
    ).scalars().all()
    return _pick_best_offer_by_subject_scores(
        list(recent),
        subject=subject,
        from_name=from_name,
        body_text=body_text,
        min_score=62.0,
    )
