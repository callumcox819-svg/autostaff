"""Запасные тексты рассылки (CH/DE), если умные пресеты пусты."""

from __future__ import annotations

# Spintax + OFFER подставится в finalize_mailing_body / apply_offer_to_text
MAILING_FALLBACK_BODIES: tuple[str, ...] = (
    "{Grüezi|Hallo|Guten Tag}! Ist der Artikel «OFFER» noch verfügbar?",
    "Hallo, ich interessiere mich für «OFFER». Ist es noch zu haben?",
    "{Grüezi|Guten Tag} – noch verfügbar: OFFER? Besten Dank.",
    "Kurze Frage: verkaufen Sie «OFFER» noch? Freundliche Grüsse.",
    "Hallo, ich würde gerne wissen, ob «OFFER» noch aktuell ist. Danke!",
)
