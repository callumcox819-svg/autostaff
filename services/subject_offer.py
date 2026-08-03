"""Глобальная тема рассылки: OFFER = название товара (для всех пользователей)."""

from __future__ import annotations

import re

from config import config

_OFFER_WORD_RE = re.compile(r"\bOFFER\b", re.IGNORECASE)
_REPLY_PREFIX_RE = re.compile(
    r"^(?:(?:re|aw|fw|fwd|wg)\s*:\s*)+",
    re.IGNORECASE,
)


def sanitize_email_subject(text: str) -> str:
    """Тема письма — одна строка без \\n (иначе SMTP: HeaderWriteError)."""
    s = (text or "").replace("\r\n", " ").replace("\n", " ").replace("\r", " ")
    s = s.replace("\u2013", "-").replace("\u2014", "-")
    s = re.sub(r"\s+", " ", s).strip()
    return s


# Legacy key — рассылка его не использует (только GLOBAL_SUBJECT_TEMPLATE).
SUBJECT_TEMPLATE_SETTING = "subject_template"

MAILING_SUBJECT_PRESETS: tuple[tuple[str, str], ...] = (
    ("re_offer", "Re: OFFER"),
    ("plain", "OFFER"),
)

def _usable_offer_title(offer_title: str) -> str:
    t = (offer_title or "").strip()
    if len(t) < 3:
        return ""
    if t.upper() in ("OFFER", "ARTIKEL", "TEST", "—", "-"):
        return ""
    return t


def global_subject_template() -> str:
    """Один шаблон на весь бот (Railway / .env)."""
    tpl = (getattr(config, "GLOBAL_SUBJECT_TEMPLATE", None) or "Re: OFFER").strip()
    return tpl or "Re: OFFER"


def render_subject_with_offer(subject_template: str, offer_title: str) -> str:
    """OFFER и {{OFFER}} → название товара; без названия в шаблоне остаётся OFFER."""
    tpl = sanitize_email_subject((subject_template or "").strip() or global_subject_template())
    title = sanitize_email_subject((offer_title or "").strip())
    replacement = title if title else "OFFER"
    out = tpl.replace("{{OFFER}}", replacement)
    out = _OFFER_WORD_RE.sub(replacement, out)
    out = sanitize_email_subject(out)
    if not out:
        out = replacement or "Anfrage"
    if len(out) > 140:
        out = out[:137] + "…"
    return out


def global_mailing_subject(offer_title: str) -> str:
    """Тема /send и тест-маил: GLOBAL_SUBJECT_TEMPLATE + подстановка OFFER."""
    return render_subject_with_offer(global_subject_template(), offer_title or "")


def pick_mailing_subject(offer_title: str) -> str:
    """
    Тема рассылки: ротация inbox-пресетов (OFFER = название лота) или один GLOBAL шаблон.
    """
    from services.mailing_deliverability import mailing_rotate_subject, pick_rotating_subject

    title = (offer_title or "").strip()
    if mailing_rotate_subject():
        return pick_rotating_subject(title, presets_only=True)
    return global_mailing_subject(title)


async def mailing_subject_for_send(session, user, offer_title: str, **_) -> str:
    """Совместимость: session/user игнорируются — тема только глобальная."""
    del session, user
    return pick_mailing_subject(offer_title)


def subject_for_offer(offer_title: str, *, template: str | None = None) -> str:
    tpl = (template or "").strip() or global_subject_template()
    return render_subject_with_offer(tpl, offer_title)


async def resolve_mailing_subject_template(session, user) -> str:
    del session, user
    return global_subject_template()


async def mailing_subject_for_user(session, user, offer_title: str) -> str:
    del session, user
    return pick_mailing_subject(offer_title)


def _mailing_subject_templates() -> tuple[str, ...]:
    """Все шаблоны темы /send — OFFER = полное item_title из БД."""
    from services.mailing_deliverability import CH_INBOX_SUBJECT_PRESETS

    seen: set[str] = set()
    out: list[str] = []
    for tpl in (*CH_INBOX_SUBJECT_PRESETS, global_subject_template(), "Re: OFFER"):
        t = sanitize_email_subject((tpl or "").strip())
        if not t or t in seen:
            continue
        seen.add(t)
        out.append(t)
    for _, t in MAILING_SUBJECT_PRESETS:
        t = sanitize_email_subject((t or "").strip())
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return tuple(out)


def _regex_from_offer_template(template: str) -> re.Pattern[str] | None:
    """Шаблон с OFFER → regex: из входящей Re: темы достать только OFFER (товар)."""
    tpl = sanitize_email_subject(template)
    if not tpl:
        return None
    if tpl.upper() == "OFFER":
        return re.compile(r"^(?P<offer>.+?)\s*$", re.IGNORECASE | re.DOTALL)

    if not _OFFER_WORD_RE.search(tpl):
        return None

    slot = "\uE000"
    tmp = _OFFER_WORD_RE.sub(slot, tpl)
    parts = tmp.split(slot)
    if len(parts) < 2:
        return None

    regex = "^"
    for i, part in enumerate(parts):
        if part:
            regex += re.escape(part)
        if i < len(parts) - 1:
            # Между фиксированными фразами пресета — только название товара (OFFER).
            regex += "(?P<offer>.+?)"
    regex += r"\s*$"
    return re.compile(regex, re.IGNORECASE | re.DOTALL)


def _compiled_inbound_offer_extractors() -> tuple[re.Pattern[str], ...]:
    specific: list[re.Pattern[str]] = []
    plain: list[re.Pattern[str]] = []
    for tpl in _mailing_subject_templates():
        rx = _regex_from_offer_template(tpl)
        if rx is None:
            continue
        if sanitize_email_subject(tpl).upper() in ("OFFER", "RE: OFFER"):
            plain.append(rx)
        else:
            specific.append(rx)
    return tuple(specific + plain)


_INBOUND_OFFER_EXTRACTORS: tuple[re.Pattern[str], ...] | None = None

_MAILING_WRAPPER_RE = re.compile(
    r"(?:"
    r"kurze\s+frage|kurze\s+anfrage|interesse\s+an|kaufinteresse|"
    r"noch\s+verf[uü]gbar|noch\s+verfugbar|guten\s+tag|haben\s+sie|"
    r"noch\s+nicht\s+verkauft|anfrage\s*:|frage\s+zu|pretenda\s+per|"
    r"noch\s+zu\s+haben|noch\s+da|noch\s+aktuell|noch\s+im\s+verkauf"
    r")",
    re.IGNORECASE,
)


def _inbound_offer_extractors() -> tuple[re.Pattern[str], ...]:
    global _INBOUND_OFFER_EXTRACTORS
    if _INBOUND_OFFER_EXTRACTORS is None:
        _INBOUND_OFFER_EXTRACTORS = _compiled_inbound_offer_extractors()
    return _INBOUND_OFFER_EXTRACTORS


def _strip_inbound_subject_trailer(subj: str) -> str:
    """«Kärcher … - noch im Verkauf» → только название (Aw:/Re: уже сняты)."""
    s = sanitize_email_subject(subj)
    s = re.sub(
        r"\s*[-–—]\s*noch im verk(?:auf)?[\.\s…]*$",
        "",
        s,
        flags=re.IGNORECASE,
    )
    s = re.sub(
        r"\s*[-–—]\s*noch verf[uü]gbar[\.\?\s…]*$",
        "",
        s,
        flags=re.IGNORECASE,
    )
    return s.strip()


def offer_title_from_inbound_subject(subject: str) -> str:
    """
    Из Re:/Aw:/WG: темы ответа продавца — только OFFER (полное item_title),
    без «Kurze Frage zu», «Guten Tag,», «noch verfügbar?» и т.д.
    """
    raw = sanitize_email_subject(subject)
    if not raw:
        return ""
    subj = _REPLY_PREFIX_RE.sub("", raw).strip()
    if not subj:
        return ""

    subj = _strip_inbound_subject_trailer(subj) or subj

    for rx in _inbound_offer_extractors():
        m = rx.match(subj)
        if not m:
            continue
        offer = sanitize_email_subject((m.group("offer") or "").strip())
        offer = _strip_inbound_subject_trailer(offer) or offer
        if len(offer) >= 3 and offer.upper() not in ("OFFER", "ARTIKEL", "TEST"):
            if offer == subj and _MAILING_WRAPPER_RE.search(subj):
                # «OFFER» plain + хвост «noch im Verkauf» — не отбрасывать
                if not re.search(r"noch\s+im\s+verk", subj, re.I):
                    continue
            if len(offer) > 140:
                offer = offer[:137].rstrip() + "…"
            return offer

    # Aw:/Re: и в теме только item_title (без пресета Kurze Frage / Interesse)
    plain = _strip_inbound_subject_trailer(subj)
    if len(plain) >= 8 and not _MAILING_WRAPPER_RE.match(plain):
        if plain.upper() not in ("OFFER", "ARTIKEL", "TEST"):
            return plain[:140]

    return ""


def subjects_for_inbound_resolve(subject: str, body: str) -> list[str]:
    """Сначала цитаты в теле (наше исходящее), потом тема письма."""
    seen: set[str] = set()
    quoted: list[str] = []

    def _add(s: str) -> None:
        t = sanitize_email_subject((s or "").strip())
        if len(t) < 8:
            return
        k = t.lower()
        if k in seen:
            return
        seen.add(k)
        quoted.append(t)

    _QUOTED_SUBJ_RE = re.compile(
        r"^(?:betreff|subject|oggetto|objet)\s*:\s*(.+)$",
        re.IGNORECASE,
    )
    _BODY_OFFER_EXTRACT = (
        re.compile(r"ob\s+(.+?)\s+noch\s+angeboten", re.IGNORECASE),
        re.compile(r"nachfragen,?\s+ob\s+(.+?)\s+noch\b", re.IGNORECASE),
        re.compile(
            r"(?:haben\s+sie|ist)\s+(.+?)\s+noch\s+(?:verfügbar|verfugbar|da|\?)",
            re.IGNORECASE,
        ),
        re.compile(r"wollte\s+nachfragen,?\s+ob\s+(.+?)\s+noch", re.IGNORECASE),
    )

    for line in (body or "").replace("\r", "\n").split("\n"):
        ls = line.strip().lstrip(">").strip()
        if len(ls) < 8:
            continue
        m_subj = _QUOTED_SUBJ_RE.match(ls)
        if m_subj:
            _add(m_subj.group(1))
            continue
        for rx in _BODY_OFFER_EXTRACT:
            m_ob = rx.search(ls)
            if not m_ob:
                continue
            extracted = sanitize_email_subject((m_ob.group(1) or "").strip())
            if len(extracted) >= 4:
                _add(extracted)
            break
        if len(ls) < 12:
            continue
        low = ls.lower()
        if not any(
            x in low
            for x in (
                "noch verfügbar",
                "noch verfugbar",
                "noch zu haben",
                "noch angeboten",
                "angeboten wird",
                "nachfragen",
                "wollte nachfragen",
                "interesse an",
                "kurze frage",
                "kurze anfrage",
                "kaufinteresse",
                "guten tag",
                "haben sie",
                "noch da",
                "noch aktuell",
                "anfrage:",
                "frage zu",
            )
        ):
            continue
        _add(ls)

    header = sanitize_email_subject((subject or "").strip())
    out = list(quoted)
    if len(header) >= 8 and header.lower() not in seen:
        out.append(header)
    return out
