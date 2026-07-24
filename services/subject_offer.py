"""Глобальная тема рассылки: OFFER = название товара (для всех пользователей)."""

from __future__ import annotations

import re

from config import config


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

_OFFER_WORD_RE = re.compile(r"\bOFFER\b")


def global_subject_template() -> str:
    """Один шаблон на весь бот (Railway / .env)."""
    tpl = (getattr(config, "GLOBAL_SUBJECT_TEMPLATE", None) or "Re: OFFER").strip()
    return tpl or "Re: OFFER"


def render_subject_with_offer(subject_template: str, offer_title: str) -> str:
    """OFFER и {{OFFER}} → название из Offer.title / item_title в raw_json."""
    tpl = sanitize_email_subject((subject_template or "").strip() or global_subject_template())
    title = sanitize_email_subject((offer_title or "").strip())
    out = tpl.replace("{{OFFER}}", title)
    out = _OFFER_WORD_RE.sub(title, out)
    out = sanitize_email_subject(out)
    if not out:
        out = title or "Anfrage"
    if len(out) > 140:
        out = out[:137] + "…"
    return out


def global_mailing_subject(offer_title: str) -> str:
    """Тема /send и тест-маил: GLOBAL_SUBJECT_TEMPLATE + подстановка OFFER."""
    return render_subject_with_offer(global_subject_template(), offer_title or "")


async def mailing_subject_for_send(session, user, offer_title: str, **_) -> str:
    """Совместимость: session/user игнорируются — тема только глобальная."""
    del session, user
    return global_mailing_subject(offer_title)


def subject_for_offer(offer_title: str, *, template: str | None = None) -> str:
    tpl = (template or "").strip() or global_subject_template()
    return render_subject_with_offer(tpl, offer_title)


async def resolve_mailing_subject_template(session, user) -> str:
    del session, user
    return global_subject_template()


async def mailing_subject_for_user(session, user, offer_title: str) -> str:
    del session, user
    return global_mailing_subject(offer_title)
