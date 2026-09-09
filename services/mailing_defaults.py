"""Запасные тексты рассылки, если умные пресеты пусты."""

from __future__ import annotations

# Spintax + OFFER подставится в finalize_mailing_body / apply_offer_to_text
MAILING_FALLBACK_BODIES: tuple[str, ...] = (
    "{Beste|Hoi|Hallo}, is «OFFER» nog beschikbaar?",
    "Hallo, ik heb interesse in «OFFER». Is het nog te koop?",
    "{Beste|Hoi} – nog beschikbaar: OFFER? Alvast bedankt.",
    "Korte vraag: verkoopt u «OFFER» nog? Groetjes.",
    "Hallo, is «OFFER» nog actueel? Dank je wel!",
    "Hi, is «OFFER» still available? Thanks!",
)
