"""Спуфинг имени в HTML-письмах (только если включён ref_toggle:spoofing)."""

from __future__ import annotations

import re

from models import User
from services.country_scope import get_scoped_setting

SPOOFING_KEY = "spoofing"
AQUA_SERVICE_KEY = "aqua_service"

_NICK_RE = re.compile(r"\{\{\s*NICK\s*\}\}", re.I)


def html_nick_key_for_service(service: str) -> str:
    s = (service or "").strip()
    return f"html_nick_{s}" if s else "html_nick"


def _setting_on(val: object) -> bool:
    return str(val or "").strip().lower() in {"1", "true", "yes", "on", "y"}


async def is_spoofing_enabled(session, user: User) -> bool:
    return _setting_on(await get_scoped_setting(session, user, SPOOFING_KEY))


async def get_spoof_display_name(session, user: User) -> str | None:
    """
    Имя для HTML From и {{NICK}}: «Имя для спуфинга» при включённом спуфинге.
    Не путать с ФИО покупателя (BUYER_NAME) и именем отправителя аккаунта.
    """
    if not await is_spoofing_enabled(session, user):
        return None
    from services.aqua_keys import aqua_service_for_html_dir, get_user_aqua_service, resolve_html_service

    keys: list[str] = []
    seen: set[str] = set()

    def _add(key: str) -> None:
        if key and key not in seen:
            seen.add(key)
            keys.append(key)

    try:
        html_svc = aqua_service_for_html_dir(await resolve_html_service(session, user))
        if html_svc:
            _add(html_nick_key_for_service(html_svc))
    except Exception:
        pass
    try:
        aqua = aqua_service_for_html_dir(await get_user_aqua_service(session, user))
        if aqua:
            _add(html_nick_key_for_service(aqua))
    except Exception:
        pass
    _add("html_nick")

    for key in keys:
        nick = (await get_scoped_setting(session, user, key) or "").strip()
        if nick:
            return nick
    return None


def apply_nick_to_html(html: str, nick: str | None) -> str:
    if not nick:
        return html
    return _NICK_RE.sub(nick, html)
