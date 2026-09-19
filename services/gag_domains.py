"""Номер домена GAG API: точное значение 1–8 из документации."""

from __future__ import annotations

from urllib.parse import urlparse

from models import User
from services.country_scope import get_scoped_setting, set_scoped_setting

AQUA_GENERATE_DOMAIN_KEY = "aqua_generate_domain"

DOMAIN_MODE_TEAM = "team"  # legacy: старое значение мигрируется в домен 1
DOMAIN_MODES_NUMBERED = tuple(str(n) for n in range(1, 9))

_BAD_HOSTS = frozenset({"undefined", "null", "none", ""})


async def get_user_gag_domain_mode(session, user: User, *, default: str = "1") -> str:
    raw = (await get_scoped_setting(session, user, AQUA_GENERATE_DOMAIN_KEY) or "").strip().lower()
    if raw in (DOMAIN_MODE_TEAM, "command", "team_domain", "0"):
        return "1"
    if raw in DOMAIN_MODES_NUMBERED:
        return raw
    return default


async def set_user_gag_domain_mode(session, user: User, mode: str) -> None:
    m = (mode or "").strip().lower()
    if m in DOMAIN_MODES_NUMBERED:
        await set_scoped_setting(session, user, AQUA_GENERATE_DOMAIN_KEY, m)
        return
    raise ValueError(f"Unknown domain mode: {mode!r}")


def gag_api_domain_for_mode(mode: str) -> int | None:
    """Точное поле domain из API: целое число 1–8."""
    m = (mode or "").strip().lower()
    if m in (DOMAIN_MODE_TEAM, "", "team"):
        return 1
    if m in DOMAIN_MODES_NUMBERED:
        return int(m)
    return 1


def profile_domain_label(mode: str) -> str:
    m = (mode or "1").strip().lower()
    if m == DOMAIN_MODE_TEAM:
        m = "1"
    if m in DOMAIN_MODES_NUMBERED:
        return f"Домен {m}"
    return m or "—"


def domain_mode_menu_options() -> tuple[tuple[str, str], ...]:
    return tuple((str(n), f"Домен {n}") for n in range(1, 9))


def finalize_gag_generated_url(url: str, *, mode: str) -> str:
    raw = (url or "").strip()
    if not raw:
        raise ValueError("Пустая ссылка от API генерации")
    if not raw.lower().startswith(("http://", "https://")):
        raw = f"https://{raw.lstrip('/')}"

    host = (urlparse(raw).hostname or "").strip().lower()
    if host and host not in _BAD_HOSTS:
        return raw

    raise ValueError(f"API вернул некорректную ссылку ({raw}). Попробуй другой домен 1–8.")


# Совместимость со старым кодом
async def get_active_domain_slot(session, user: User, *, default: int = 1) -> int:
    mode = await get_user_gag_domain_mode(session, user)
    return int(mode)


async def get_user_generate_domain(session, user: User) -> int | None:
    mode = await get_user_gag_domain_mode(session, user)
    return gag_api_domain_for_mode(mode)
