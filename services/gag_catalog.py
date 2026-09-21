"""GAG / Швейцария: площадки объявлений и код сервиса для /generate."""

from __future__ import annotations

# stored code, UI label, API /generate service
GAG_CH_PLATFORMS: tuple[tuple[str, str, str], ...] = (
    ("ricardo_ch", "Ricardo", "ricardo_ch"),
    ("markt_ch", "Markt.ch", "posta_ch"),
)

_STORED = {code for code, _, _ in GAG_CH_PLATFORMS}
_ALIASES: dict[str, str] = {
    "ricardo": "ricardo_ch",
    "ricardo.ch": "ricardo_ch",
    "markt": "markt_ch",
    "markt.ch": "markt_ch",
    "markt_ch": "markt_ch",
    "posta_ch": "markt_ch",
    "post_ch": "markt_ch",
    "post.ch": "markt_ch",
    "posta.ch": "markt_ch",
}


def normalize_gag_service_code(code: str | None) -> str:
    s = (code or "").strip().lower()
    if s in _STORED:
        return s
    return _ALIASES.get(s, "ricardo_ch")


def gag_generate_service(code: str | None) -> str:
    """Код в GAG /generate: Markt.ch → posta_ch, Ricardo → ricardo_ch."""
    stored = normalize_gag_service_code(code)
    for sid, _label, gen in GAG_CH_PLATFORMS:
        if sid == stored:
            return gen
    return "ricardo_ch"


def gag_service_label(code: str | None) -> str:
    stored = normalize_gag_service_code(code)
    for sid, label, _gen in GAG_CH_PLATFORMS:
        if sid == stored:
            return label
    return stored or "—"


def is_gag_service_code(code: str | None) -> bool:
    s = (code or "").strip().lower()
    return s in _STORED or s in _ALIASES
