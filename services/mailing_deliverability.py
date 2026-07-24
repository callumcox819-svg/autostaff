"""
Inbox placement — чтобы письма попадали в Inbox получателя, а не в Spam.

Не «доставка SMTP» (250 OK), а контент + паттерн отправки под фильтры Gmail/Outlook.
"""

from __future__ import annotations

import os
import random
import re

from email.message import EmailMessage

LINK_RE = re.compile(r"https?://[^\s<>\"']+", re.I)
LINK_PLACEHOLDER_RE = re.compile(r"\{\{\s*LINK\s*\}\}", re.I)
HTML_TAG_RE = re.compile(r"<[^>]+>")
FAKE_REPLY_SUBJ_RE = re.compile(r"^\s*(re|aw|fwd|fw)\s*:\s*", re.I)
# Триггеры массовой рассылки / спама (DE + EN)
_SPAM_PHRASES_RE = re.compile(
    r"\b("
    r"click here|act now|limited time|free money|winner|congratulations|"
    r"unsubscribe|klicken sie|jetzt kaufen|gratis|gewonnen|dringend|"
    r"100%|!!!+|urgent|offer expires"
    r")\b",
    re.I,
)
_CAPS_WORD_RE = re.compile(r"\b[A-ZÄÖÜ]{5,}\b")

# Темы как у обычного покупателя (без ложного Re: — фильтры это режут)
CH_INBOX_SUBJECT_PRESETS: tuple[str, ...] = (
    "OFFER",
    "Kurze Frage zu OFFER",
    "Noch verfügbar? OFFER",
    "Interesse an OFFER",
    "OFFER – noch da?",
    "Frage zu OFFER",
    "Anfrage: OFFER",
    "OFFER – noch aktuell?",
    "Kurze Anfrage zu OFFER",
)

_INBOX_OPENERS: tuple[str, ...] = (
    "",
    "Grüezi!\n\n",
    "Guten Tag,\n\n",
    "Hallo,\n\n",
)

# Лёгкая уникализация тела (каждое письмо чуть отличается)
_INBOX_CLOSINGS: tuple[str, ...] = (
    "",
    "Danke!",
    "Freundliche Grüsse",
    "Besten Dank",
    "LG",
    "Vielen Dank im Voraus",
)


def _env_on(name: str, *, default: str = "1") -> bool:
    return (os.getenv(name, default) or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def mailing_plain_only() -> bool:
    """Plain text — HTML multipart чаще уходит в Spam на cold mail."""
    return _env_on("MAILING_PLAIN_ONLY", default="1")


def mailing_minimal_headers() -> bool:
    """From = реальный Gmail, без marketing display name."""
    return _env_on("MAILING_MINIMAL_HEADERS", default="1")


def mailing_strip_link() -> bool:
    """Без URL в первом касании — ссылка в ответе/HTML (inbox-safe)."""
    return _env_on("MAILING_STRIP_LINK", default="1")


def mailing_ehlo_name() -> str | None:
    raw = (os.getenv("MAILING_EHLO_NAME") or os.getenv("SMTP_EHLO_HOSTNAME") or "").strip()
    return raw[:253] if raw else None


def inbox_stagger_ms() -> int:
    """Микро-задержка старта каждого ящика внутри волны (не одновременный залп)."""
    return max(0, min(400, int(os.getenv("INBOX_STAGGER_MS", "60"))))


def inbox_account_gap_sec() -> float:
    """Пауза между волнами с одного Gmail (если адресов > ящиков)."""
    return max(0.0, min(3.0, float(os.getenv("INBOX_ACCOUNT_GAP_SEC", "0.35"))))


def burst_target_max_sec() -> float:
    """Целевое время burst на всю очередь (адаптивный gap между волнами)."""
    return max(2.0, min(60.0, float(os.getenv("BURST_TARGET_MAX_SEC", "10"))))


def burst_wave_gap_sec(num_waves: int, *, estimated_wave_sec: float = 3.0) -> float:
    """
    Inbox-safe пауза между волнами.
    При BURST_ADAPTIVE_GAP=1 укладывается в BURST_TARGET_MAX_SEC (по умолчанию 10с).
    """
    if num_waves <= 1:
        return 0.0
    base = inbox_account_gap_sec()
    if not _env_on("BURST_ADAPTIVE_GAP", default="1"):
        return base
    budget = max(0.0, burst_target_max_sec() - estimated_wave_sec)
    if budget <= 0:
        return max(0.08, base)
    adaptive = budget / max(1, num_waves - 1)
    return max(0.08, min(1.5, min(base + 0.05, adaptive)))


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
    # Re: OFFER из GLOBAL_SUBJECT_TEMPLATE не снимаем — осознанный префикс для инбокса.
    s = re.sub(r"^\s*betreff\s*:\s*", "", s, flags=re.I).strip()
    s = re.sub(r"\s+", " ", s)
    if len(s) > 78:
        s = s[:75] + "…"
    return s or "Anfrage"


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
    """Микро-уникализация — разные подписи и приветствия."""
    b = (body or "").strip()
    opener = random.choice(_INBOX_OPENERS)
    if opener and not b.lower().startswith(("grüezi", "guten tag", "hallo", "hello")):
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


def finalize_inbox_mail(subject: str, body: str) -> tuple[str, str]:
    """Финальная обработка subject+body перед SMTP (inbox placement)."""
    subj = sanitize_subject_for_inbox(subject)
    b = apply_mailing_body_policy(body)
    return subj, b


def pick_rotating_subject(offer_title: str, *, user_template: str | None = None) -> str:
    from services.subject_offer import global_subject_template, render_subject_with_offer

    pool: list[str] = list(CH_INBOX_SUBJECT_PRESETS)
    ut = (user_template or "").strip()
    if ut:
        pool = [ut]
    else:
        gt = (global_subject_template() or "").strip()
        if gt:
            pool.append(gt)
    tpl = random.choice(pool)
    return render_subject_with_offer(tpl, offer_title)


def log_deliverability_profile(logger) -> None:
    logger.info(
        "Inbox placement: plain=%s minimal_hdr=%s no_links=%s "
        "stagger_ms=%s wave_gap=%.2fs burst_target=%.0fs ehlo=%s",
        mailing_plain_only(),
        mailing_minimal_headers(),
        mailing_strip_link(),
        inbox_stagger_ms(),
        inbox_account_gap_sec(),
        burst_target_max_sec(),
        mailing_ehlo_name() or "(default)",
    )
