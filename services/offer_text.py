"""Подстановка названия товара (OFFER) в текст письма."""

from __future__ import annotations

import re

from utils.re_literal import re_sub_literal

_OFFER_TOKEN_RE = re.compile(r"\bOFFER\b", re.IGNORECASE)


def apply_offer_to_text(text: str, offer_title: str) -> str:
    """OFFER / Offer / {{OFFER}} / «OFFER» → название объявления."""
    txt = text or ""
    title = (offer_title or "").strip()
    if not title:
        return txt
    for needle in ('{{OFFER}}', '"OFFER"', "'OFFER'", "«OFFER»", '"Offer"', "'Offer'", "«Offer»"):
        txt = txt.replace(needle, title)
    # title как literal — иначе re.sub ест \512 в названии как octal escape
    return re_sub_literal(_OFFER_TOKEN_RE, title, txt)


def ensure_item_title_in_body(body: str, offer_title: str) -> str:
    """
    Если в теле нет названия товара — дописать строку на DE.
    Иначе Gmail видит «массовый шаблон»: subject = товар, body без названия.
    """
    b = (body or "").strip()
    t = (offer_title or "").strip()
    if not b or not t or len(t) < 3:
        return body
    if t.lower() in b.lower():
        return body
    return f"{b}\n\nEs geht um Ihr Inserat: {t}."


def finalize_mailing_body(body: str, offer_title: str) -> str:
    out = apply_offer_to_text(body or "", offer_title or "")
    return ensure_item_title_in_body(out, offer_title or "")
