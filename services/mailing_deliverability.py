"""
Inbox placement — чтобы письма попадали в Inbox получателя, а не в Spam.

Глобально для всей рассылки (/send, тест-мейл): контент + паузы BURST + заголовки.
Не привязано к площадке/локали сервиса.
"""

from __future__ import annotations

import os
import random
import re

LINK_RE = re.compile(r"https?://[^\s<>\"']+", re.I)
LINK_PLACEHOLDER_RE = re.compile(r"\{\{\s*LINK\s*\}\}", re.I)
HTML_TAG_RE = re.compile(r"<[^>]+>")
FAKE_REPLY_SUBJ_RE = re.compile(r"^\s*(?:re|aw|fwd|fw|wg)\s*:\s*", re.I)
_OFFER_TOKEN_RE = re.compile(r"\bOFFER\b", re.IGNORECASE)
_SPAM_PHRASES_RE = re.compile(
    r"\b("
    r"click here|act now|limited time|free money|winner|congratulations|"
    r"unsubscribe|klicken sie|jetzt kaufen|gratis|gewonnen|dringend|"
    r"klik hier|nu kopen|beperkte tijd|"
    r"100%|!!!+|urgent|offer expires"
    r")\b",
    re.I,
)
_CAPS_WORD_RE = re.compile(r"\b[A-ZÄÖÜ]{5,}\b")

# Основные темы cold outreach (OFFER → название товара). Без фейкового Re:.
INBOX_SUBJECT_PRESETS: tuple[str, ...] = (
    "OFFER",
    "Vraag over OFFER",
    "Nog beschikbaar? OFFER",
    "Interesse in OFFER",
    "OFFER – nog te koop?",
    "Korte vraag over OFFER",
    "OFFER nog actueel?",
    "Is OFFER nog beschikbaar?",
    "Nog niet verkocht? OFFER",
    "Hallo, OFFER nog te koop?",
    "Vraag: OFFER",
    "OFFER – nog aanwezig?",
    "Beste, OFFER nog beschikbaar?",
    # короткие EN/универсальные — меньше «шаблонной» одинаковости
    "Question about OFFER",
    "Is OFFER still available?",
)

# Legacy alias (старые импорты)
CH_INBOX_SUBJECT_PRESETS = INBOX_SUBJECT_PRESETS

_INBOX_OPENERS: tuple[str, ...] = (
    "",
    "Beste,\n\n",
    "Hoi,\n\n",
    "Hallo,\n\n",
    "Goedemiddag,\n\n",
    "Hi,\n\n",
)

_INBOX_CLOSINGS: tuple[str, ...] = (
    "",
    "Dank je!",
    "Alvast bedankt",
    "Groetjes",
    "Met vriendelijke groet",
    "Bedankt!",
    "Thanks!",
)

# Короткие тела как у успешных inbox-писем (без ссылок / OFFER в теле)
INBOX_SUCCESS_BODIES: tuple[str, ...] = (
    "Beste, is uw advertentie nog beschikbaar?",
    "Hallo, is uw advertentie nog te koop?",
    "Hoi, is dit nog actueel?",
    "Beste, is het artikel nog beschikbaar?",
    "Hallo, nog te koop?",
    "Goedemiddag, is dit nog niet verkocht?",
    "Hi, is this still available?",
    "Hello, is your listing still for sale?",
)


def _env_on(name: str, *, default: str = "1") -> bool:
    return (os.getenv(name, default) or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def mailing_fast_mode() -> bool:
    """Старый агрессивный BURST (почти без пауз)."""
    return _env_on("MAILING_FAST_MODE", default="0")


def mailing_inbox_success_profile() -> bool:
    """Короткий inbox-текст вместо длинных умных пресетов. По умолчанию вкл."""
    return _env_on("MAILING_INBOX_SUCCESS_PROFILE", default="1")


def pick_inbox_success_body() -> str:
    return random.choice(INBOX_SUCCESS_BODIES)


def mailing_subject_display_title(offer_title: str) -> str:
    t = (offer_title or "").strip()
    if len(t) < 3 or t.upper() in ("OFFER", "TEST", "ARTIKEL", "—", "-", "ADVERTENTIE"):
        return "advertentie"
    if len(t) > 56:
        return t[:53].rstrip() + "…"
    return t


def build_inbox_mailing_copy(offer_title: str) -> tuple[str, str]:
    """Subject + body: короткий plain cold mail без Re: и без ссылок."""
    label = mailing_subject_display_title(offer_title)
    subj = pick_rotating_subject(label, presets_only=True)
    body = pick_inbox_success_body()
    return finalize_inbox_mail(subj, body, offer_title=label)


def mailing_plain_only() -> bool:
    return _env_on("MAILING_PLAIN_ONLY", default="1")


def mailing_minimal_headers() -> bool:
    return _env_on("MAILING_MINIMAL_HEADERS", default="0")


def mailing_body_variation() -> bool:
    """Случайные приветствия/подписи — по умолчанию вкл."""
    return _env_on("MAILING_BODY_VARIATION", default="1")


def mailing_strip_link() -> bool:
    return _env_on("MAILING_STRIP_LINK", default="1")


def mailing_ehlo_name() -> str | None:
    raw = (os.getenv("MAILING_EHLO_NAME") or os.getenv("SMTP_EHLO_HOSTNAME") or "").strip()
    if raw:
        return raw[:253]
    return "[127.0.0.1]"


def mailing_max_per_account_hour() -> int:
    """Мягкий лимит писем с одного Gmail за скользящий час (0 = выкл.)."""
    return max(0, min(500, int(os.getenv("MAILING_MAX_PER_ACCOUNT_HOUR", "40"))))


def inbox_stagger_ms() -> int:
    default = "0" if mailing_fast_mode() else "80"
    return max(0, min(400, int(os.getenv("INBOX_STAGGER_MS", default))))


def inbox_account_gap_sec() -> float:
    default = "0.0" if mailing_fast_mode() else "0.4"
    return max(0.0, min(3.0, float(os.getenv("INBOX_ACCOUNT_GAP_SEC", default))))


def burst_target_max_sec() -> float:
    default = "2" if mailing_fast_mode() else "18"
    return max(2.0, min(120.0, float(os.getenv("BURST_TARGET_MAX_SEC", default))))


def burst_single_proxy_wave_gap_sec() -> float:
    default = "0.05" if mailing_fast_mode() else "0.35"
    return max(0.0, min(2.0, float(os.getenv("BURST_SINGLE_PROXY_WAVE_GAP_SEC", default))))


def burst_wave_gap_sec(num_waves: int, *, estimated_wave_sec: float = 3.0) -> float:
    if num_waves <= 1:
        return 0.0
    base = inbox_account_gap_sec()
    if not _env_on("BURST_ADAPTIVE_GAP", default="1"):
        return base
    budget = max(0.0, burst_target_max_sec() - estimated_wave_sec)
    min_default = "0.0" if mailing_fast_mode() else "0.15"
    min_gap = max(0.0, min(1.0, float(os.getenv("BURST_MIN_WAVE_GAP_SEC", min_default))))
    if budget <= 0:
        return max(min_gap, base)
    adaptive = budget / max(1, num_waves - 1)
    return max(min_gap, min(1.5, max(base, min(base + 0.15, adaptive))))


def inbox_max_body_chars() -> int:
    return max(80, min(2000, int(os.getenv("INBOX_MAX_BODY_CHARS", "900"))))


def strip_links_from_body(body: str) -> str:
    out = LINK_PLACEHOLDER_RE.sub("", body or "")
    out = LINK_RE.sub("", out)
    out = re.sub(r"[ \t]+\n", "\n", out)
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.strip()


def sanitize_subject_for_inbox(subject: str) -> str:
    s = (subject or "").replace("\r\n", " ").replace("\n", " ").strip()
    # Cold outreach: снимаем фейковый Re:/Aw: (нет истории треда).
    while FAKE_REPLY_SUBJ_RE.match(s):
        s = FAKE_REPLY_SUBJ_RE.sub("", s).strip()
    s = re.sub(r"^\s*(?:betreff|onderwerp|subject)\s*:\s*", "", s, flags=re.I).strip()
    s = re.sub(r"\s+", " ", s)
    if len(s) > 78:
        s = s[:75] + "…"
    return s or "Vraag"


def sanitize_body_for_inbox(body: str) -> str:
    out = HTML_TAG_RE.sub("", body or "")
    out = _SPAM_PHRASES_RE.sub("", out)
    out = _CAPS_WORD_RE.sub(lambda m: m.group(0).capitalize(), out)
    out = re.sub(r"!{2,}", "!", out)
    out = re.sub(r"[ \t]+\n", "\n", out)
    out = re.sub(r"\n{3,}", "\n\n", out).strip()
    cap = inbox_max_body_chars()
    if len(out) > cap:
        out = out[: cap - 1] + "…"
    return out


def add_inbox_body_variation(body: str) -> str:
    if not mailing_body_variation():
        return (body or "").strip()
    b = (body or "").strip()
    opener = random.choice(_INBOX_OPENERS)
    starts = ("beste", "hoi", "goedemiddag", "hallo", "hello", "hi", "grüezi", "guten tag")
    if opener and not b.lower().startswith(starts):
        b = f"{opener.strip()}\n\n{b}" if opener.strip() else b
    closing = random.choice(_INBOX_CLOSINGS)
    if not closing:
        return b.strip()
    if closing.lower() in b.lower()[-40:]:
        return b.strip()
    return f"{b}\n\n{closing}".strip()


def apply_mailing_body_policy(body: str) -> str:
    out = sanitize_body_for_inbox(body)
    if mailing_strip_link():
        out = strip_links_from_body(out)
    out = add_inbox_body_variation(out)
    return out.strip()


def finalize_inbox_mail(subject: str, body: str, *, offer_title: str = "") -> tuple[str, str]:
    subj = sanitize_subject_for_inbox(subject)
    b = apply_mailing_body_policy(body)
    subj, b = _scrub_offer_leaks(subj, b, offer_title)
    return subj, b


def _scrub_offer_leaks(subject: str, body: str, offer_title: str) -> tuple[str, str]:
    title = (offer_title or "").strip()

    def _repl_body(text: str) -> str:
        from utils.re_literal import re_sub_literal

        if not text:
            return text
        if title:
            return re_sub_literal(_OFFER_TOKEN_RE, title, text)
        return re_sub_literal(_OFFER_TOKEN_RE, "uw advertentie", text)

    return subject, _repl_body(body)


def mailing_rotate_subject() -> bool:
    return _env_on("MAILING_ROTATE_SUBJECT", default="1")


def pick_rotating_subject(
    offer_title: str,
    *,
    user_template: str | None = None,
    presets_only: bool = False,
) -> str:
    from services.subject_offer import global_subject_template, render_subject_with_offer

    pool: list[str] = list(INBOX_SUBJECT_PRESETS)
    ut = (user_template or "").strip()
    if ut:
        pool = [ut]
    elif not presets_only:
        gt = (global_subject_template() or "").strip()
        if gt:
            pool.append(gt)
    tpl = random.choice(pool)
    return render_subject_with_offer(tpl, offer_title)


def log_deliverability_profile(logger) -> None:
    logger.info(
        "Inbox placement: success_profile=%s rotate_subject=%s plain=%s minimal_hdr=%s "
        "body_var=%s no_links=%s fast=%s stagger_ms=%s wave_gap=%.2fs burst_target=%.0fs "
        "max_per_acc_h=%s ehlo=%s",
        mailing_inbox_success_profile(),
        mailing_rotate_subject(),
        mailing_plain_only(),
        mailing_minimal_headers(),
        mailing_body_variation(),
        mailing_strip_link(),
        mailing_fast_mode(),
        inbox_stagger_ms(),
        inbox_account_gap_sec(),
        burst_target_max_sec(),
        mailing_max_per_account_hour(),
        mailing_ehlo_name() or "(default)",
    )
