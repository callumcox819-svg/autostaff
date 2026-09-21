"""Извлечение одного адреса для SMTP (не цитата из тела письма)."""

from __future__ import annotations

import re

# Один адрес; не жадный — не съедаем хвост цитаты.
_ADDR_RE = re.compile(
    r"[a-zA-Z0-9][a-zA-Z0-9._%+\-]*@[a-zA-Z0-9][a-zA-Z0-9.\-]*\.[a-zA-Z]{2,}"
)


def extract_email_address(raw: str) -> str:
    """
    Вернуть первый email из строки.
    Пусто, если в тексте нет адреса или это явно не адрес (многострочная цитата).
    """
    s = (raw or "").strip()
    if not s:
        return ""

    if "\n" in s or "\r" in s or len(s) > 120:
        m = _ADDR_RE.search(s)
        return (m.group(0) if m else "").strip().lower()

    bracket = re.search(r"<([^>@\s]+@[^>]+)>", s)
    if bracket:
        s = bracket.group(1).strip()

    s = s.strip().strip("<>").lower()
    if _ADDR_RE.fullmatch(s):
        return s

    m = _ADDR_RE.search(s)
    return (m.group(0) if m else "").strip().lower()


def is_valid_smtp_recipient(email: str) -> bool:
    em = extract_email_address(email)
    return bool(em) and "@" in em and "\n" not in em and "\r" not in em and len(em) <= 120


def canonicalize_dialog_email(email: str) -> str:
    """Ключ диалога: lower + Gmail без точек/+tag (как IMAP и HTML)."""
    e = extract_email_address(email) or (email or "").strip().lower()
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


def dialog_email_match_keys(email: str) -> list[str]:
    """Все формы адреса, которыми мог быть записан ConversationLink / IncomingMail."""
    raw = (extract_email_address(email) or (email or "").strip().lower()).strip().lower()
    canon = canonicalize_dialog_email(email)
    keys: list[str] = []
    for k in (raw, canon):
        if k and k not in keys:
            keys.append(k)
    return keys
