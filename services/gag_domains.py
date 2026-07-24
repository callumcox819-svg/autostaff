"""Домен GAG в профиле: команда (без domain в API) или Домен 1–4 → API 5–8."""

from __future__ import annotations

from urllib.parse import urlparse

from models import User
from services.user_settings import get_user_setting, set_user_setting

AQUA_GENERATE_DOMAIN_KEY = "aqua_generate_domain"

DOMAIN_MODE_TEAM = "team"
DOMAIN_MODES_NUMBERED = ("1", "2", "3", "4")

_BAD_HOSTS = frozenset({"undefined", "null", "none", ""})


async def get_user_gag_domain_mode(session, user: User, *, default: str = DOMAIN_MODE_TEAM) -> str:
    raw = (await get_user_setting(session, user, AQUA_GENERATE_DOMAIN_KEY) or "").strip().lower()
    if raw in (DOMAIN_MODE_TEAM, "command", "team_domain", "0"):
        return DOMAIN_MODE_TEAM
    if raw in DOMAIN_MODES_NUMBERED:
        return raw
    if raw.isdigit():
        n = int(raw)
        if 5 <= n <= 8:
            return str(n - 4)
        if 1 <= n <= 4:
            return str(n)
    return default


async def set_user_gag_domain_mode(session, user: User, mode: str) -> None:
    m = (mode or "").strip().lower()
    if m == DOMAIN_MODE_TEAM:
        await set_user_setting(session, user, AQUA_GENERATE_DOMAIN_KEY, DOMAIN_MODE_TEAM)
        return
    if m in DOMAIN_MODES_NUMBERED:
        await set_user_setting(session, user, AQUA_GENERATE_DOMAIN_KEY, m)
        return
    raise ValueError(f"Unknown domain mode: {mode!r}")


def gag_api_domain_for_mode(mode: str) -> int | None:
    """
    None — домен команды (поле domain в JSON не отправляем).
    5–8 — для «Домен 1» … «Домен 4» (слот + 4).
    """
    m = (mode or "").strip().lower()
    if m in (DOMAIN_MODE_TEAM, "", "team"):
        return None
    if m in DOMAIN_MODES_NUMBERED:
        return int(m) + 4
    return None


def profile_domain_label(mode: str) -> str:
    m = (mode or DOMAIN_MODE_TEAM).strip().lower()
    if m == DOMAIN_MODE_TEAM:
        return "Домен команды"
    if m in DOMAIN_MODES_NUMBERED:
        return f"Домен {m}"
    return m or "—"


def domain_mode_menu_options() -> tuple[tuple[str, str], ...]:
    return (
        (DOMAIN_MODE_TEAM, "Домен команды"),
        ("1", "Домен 1"),
        ("2", "Домен 2"),
        ("3", "Домен 3"),
        ("4", "Домен 4"),
    )


def finalize_gag_generated_url(url: str, *, mode: str) -> str:
    raw = (url or "").strip()
    if not raw:
        raise ValueError("Пустая ссылка от GAG API")
    if not raw.lower().startswith(("http://", "https://")):
        raw = f"https://{raw.lstrip('/')}"

    host = (urlparse(raw).hostname or "").strip().lower()
    if host and host not in _BAD_HOSTS:
        return raw

    if (mode or "").strip().lower() == DOMAIN_MODE_TEAM:
        raise ValueError(
            "GAG вернул некорректную ссылку. Выбери «Домен команды» в профиле и проверь apikey в панели GAG."
        )
    raise ValueError(f"GAG вернул некорректную ссылку ({raw}). Попробуй другой «Домен 1–4» или команду.")


# Совместимость со старым кодом
async def get_active_domain_slot(session, user: User, *, default: int = 1) -> int:
    mode = await get_user_gag_domain_mode(session, user)
    if mode == DOMAIN_MODE_TEAM:
        return 0
    return int(mode)


async def get_user_generate_domain(session, user: User) -> int | None:
    mode = await get_user_gag_domain_mode(session, user)
    return gag_api_domain_for_mode(mode)
