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
_OFFER_TOKEN_RE = re.compile(r"\bOFFER\b", re.IGNORECASE)
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

# Темы как у обычного покупателя; в каждой MUST быть OFFER → название товара
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
    "Haben Sie OFFER noch?",
    "Ist OFFER noch zu haben?",
    "Noch nicht verkauft? OFFER",
    "Kaufinteresse: OFFER",
    "OFFER – noch im Verkauf?",
    "Guten Tag, OFFER noch verfügbar?",
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

# Короткие тексты как в успешном inbox .eml (без OFFER/ссылок в теле)
INBOX_SUCCESS_BODIES: tuple[str, ...] = (
    "Guten Tag, ist Ihr Inserat noch zu haben?",
    "Hallo, ist Ihr Inserat noch verfügbar?",
    "Grüezi, ist Ihr Inserat noch aktuell?",
    "Guten Tag, ist der Artikel noch zu haben?",
    "Hallo, noch zu verkaufen?",
)


def mailing_inbox_success_profile() -> bool:
    """Опционально: короткий inbox-текст без умных пресетов (выкл. по умолчанию)."""
    return _env_on("MAILING_INBOX_SUCCESS_PROFILE", default="0")


def pick_inbox_success_body() -> str:
    return random.choice(INBOX_SUCCESS_BODIES)


def mailing_subject_display_title(offer_title: str) -> str:
    """В теме — короткая подпись; в спам уходит голое OFFER или простыня."""
    t = (offer_title or "").strip()
    if len(t) < 3 or t.upper() in ("OFFER", "TEST", "ARTIKEL", "—", "-"):
        return "Anzeige"
    if len(t) > 56:
        return t[:53].rstrip() + "…"
    return t


def build_inbox_mailing_copy(offer_title: str) -> tuple[str, str]:
    """
    Subject + body как в успешном Kurze Anfrage zu Anzeige.eml:
    plain, короткий DE, без Re: и без шаблонного OFFER в теле.
    """
    label = mailing_subject_display_title(offer_title)
    subj = pick_rotating_subject(label, presets_only=True)
    body = pick_inbox_success_body()
    return finalize_inbox_mail(subj, body, offer_title=label)


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
    """True = только email в From (хуже для inbox). False = имя + Reply-To как у Gmail-клиента."""
    return _env_on("MAILING_MINIMAL_HEADERS", default="0")


def mailing_body_variation() -> bool:
    """Случайные приветствия/подписи — по умолчанию выкл., текст как в пресете."""
    return _env_on("MAILING_BODY_VARIATION", default="0")


def mailing_strip_link() -> bool:
    """Без URL в первом касании — ссылка в ответе/HTML (inbox-safe)."""
    return _env_on("MAILING_STRIP_LINK", default="1")


def mailing_ehlo_name() -> str | None:
    raw = (os.getenv("MAILING_EHLO_NAME") or os.getenv("SMTP_EHLO_HOSTNAME") or "").strip()
    if raw:
        return raw[:253]
    # Как у Gmail mobile при SMTP — не FQDN сервера Railway
    return "[127.0.0.1]"


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
    if not mailing_body_variation():
        return (body or "").strip()
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


def finalize_inbox_mail(subject: str, body: str, *, offer_title: str = "") -> tuple[str, str]:
    """Финальная обработка subject+body перед SMTP (inbox placement)."""
    subj = sanitize_subject_for_inbox(subject)
    b = apply_mailing_body_policy(body)
    subj, b = _scrub_offer_leaks(subj, b, offer_title)
    return subj, b


def _scrub_offer_leaks(subject: str, body: str, offer_title: str) -> tuple[str, str]:
    """Убрать необработанный Offer/OFFER только из тела (тема уже из GLOBAL_SUBJECT_TEMPLATE)."""
    title = (offer_title or "").strip()

    def _repl_body(text: str) -> str:
        if not text:
            return text
        if title:
            return _OFFER_TOKEN_RE.sub(title, text)
        return _OFFER_TOKEN_RE.sub("Ihr Inserat", text)

    return subject, _repl_body(body)


def mailing_rotate_subject() -> bool:
    """Случайная тема из CH_INBOX_SUBJECT_PRESETS (всегда с подстановкой OFFER)."""
    return _env_on("MAILING_ROTATE_SUBJECT", default="1")


def pick_rotating_subject(
    offer_title: str,
    *,
    user_template: str | None = None,
    presets_only: bool = False,
) -> str:
    from services.subject_offer import global_subject_template, render_subject_with_offer

    pool: list[str] = list(CH_INBOX_SUBJECT_PRESETS)
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
        "Inbox placement: success_profile=%s rotate_subject=%s plain=%s minimal_hdr=%s body_var=%s no_links=%s "
        "stagger_ms=%s wave_gap=%.2fs burst_target=%.0fs ehlo=%s",
        mailing_inbox_success_profile(),
        mailing_rotate_subject(),
        mailing_plain_only(),
        mailing_minimal_headers(),
        mailing_body_variation(),
        mailing_strip_link(),
        inbox_stagger_ms(),
        inbox_account_gap_sec(),
        burst_target_max_sec(),
        mailing_ehlo_name() or "(default)",
    )
