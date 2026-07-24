"""Домены GAG (слоты 1–8): базовый URL команды + активный слот для POST /generate."""

from __future__ import annotations

from urllib.parse import urlparse

from models import User
from services.user_settings import get_user_setting, set_user_setting

AQUA_GENERATE_DOMAIN_KEY = "aqua_generate_domain"
GAG_DOMAIN_BASE_PREFIX = "gag_domain_base_"

_BAD_HOSTS = frozenset({"undefined", "null", "none", ""})


def domain_base_setting_key(slot: int) -> str:
    n = max(1, min(8, int(slot)))
    return f"{GAG_DOMAIN_BASE_PREFIX}{n}"


async def get_domain_base(session, user: User, slot: int) -> str:
    key = domain_base_setting_key(slot)
    raw = (await get_user_setting(session, user, key) or "").strip().rstrip("/")
    if not raw:
        return ""
    if not raw.lower().startswith(("http://", "https://")):
        raw = f"https://{raw.lstrip('/')}"
    return raw.rstrip("/")


async def set_domain_base(session, user: User, slot: int, base: str | None) -> None:
    key = domain_base_setting_key(slot)
    v = (base or "").strip().rstrip("/")
    if v and not v.lower().startswith(("http://", "https://")):
        v = f"https://{v.lstrip('/')}"
    await set_user_setting(session, user, key, v or None)


async def clear_domain_base(session, user: User, slot: int) -> None:
    await set_domain_base(session, user, slot, None)


async def get_active_domain_slot(session, user: User, *, default: int = 1) -> int:
    raw = (await get_user_setting(session, user, AQUA_GENERATE_DOMAIN_KEY) or "").strip()
    if raw.isdigit():
        n = int(raw)
        if 1 <= n <= 8:
            return n
    return max(1, min(8, int(default)))


async def set_active_domain_slot(session, user: User, slot: int) -> None:
    n = max(1, min(8, int(slot)))
    await set_user_setting(session, user, AQUA_GENERATE_DOMAIN_KEY, str(n))


def slot_button_label(slot: int, *, active: int, has_base: bool) -> str:
    if int(slot) == int(active) and has_base:
        return f"Сменить #{slot}"
    if has_base:
        return f"#{slot} · выбрать"
    return f"Установить #{slot}"


def profile_domain_summary(active: int, base: str) -> str:
    b = (base or "").strip()
    if b:
        host = urlparse(b).hostname or b.replace("https://", "").replace("http://", "")[:40]
        return f"#{active} · {host}"
    return f"#{active} · не задан (укажи домен команды)"


def normalize_gag_generated_url(url: str, *, domain_slot: int, domain_base: str) -> str:
    """
    GAG иногда отдаёт https://undefined/get/ID — подставляем базу из профиля (слот 1–8).
    """
    raw = (url or "").strip()
    if not raw:
        raise ValueError("Пустая ссылка от API")

    if not raw.lower().startswith(("http://", "https://")):
        raw = f"https://{raw.lstrip('/')}"

    p = urlparse(raw)
    host = (p.hostname or "").strip().lower()
    path = p.path or ""
    if not path.startswith("/"):
        path = f"/{path}" if path else ""

    if host not in _BAD_HOSTS and host:
        return raw

    base = (domain_base or "").strip().rstrip("/")
    if not base:
        raise ValueError(
            f"GAG вернул некорректный домен ({raw}). "
            f"Профиль → Домен GAG → Установить #{domain_slot} — введи URL домена команды."
        )

    q = f"?{p.query}" if p.query else ""
    frag = f"#{p.fragment}" if p.fragment else ""
    return f"{base}{path or '/'}{q}{frag}"
