"""Сервисы и ключи для генерации ссылок (список: AQUA_SERVICES или папки data/HTML/)."""

from __future__ import annotations

import os
import re
from pathlib import Path

from config import config
from models import User
from region import AQUA_DEFAULT_SERVICE, HTML_DATA_DIR, TEAM_NAME
from services.user_settings import get_user_setting, set_user_setting
from utils.secrets import clean_secret

AQUA_SERVICE_KEY = "aqua_service"

AQUA_USER_API_KEY_SETTING = "aqua_user_api_key"

AQUA_PROFILE_TITLE_KEY = "aqua_profile_title"
AQUA_PROFILE_NAME_KEY = "aqua_profile_name"
AQUA_PROFILE_ADDRESS_KEY = "aqua_profile_address"

AQUA_GENERATE_DOMAIN_KEY = "aqua_generate_domain"


def _services_from_env() -> tuple[str, ...]:
    raw = (os.getenv("AQUA_SERVICES") or "").strip()
    if not raw:
        return ()
    out: list[str] = []
    seen: set[str] = set()
    for part in re.split(r"[,;\s]+", raw):
        s = part.strip().lower()
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)
    return tuple(out)


def _services_from_html_dirs() -> tuple[str, ...]:
    """Авто-сервисы: папки data/HTML/<code>/ с confirmation.html."""
    root = Path("data") / (HTML_DATA_DIR or "HTML")
    if not root.is_dir():
        return ()
    out: list[str] = []
    for p in sorted(root.iterdir()):
        if not p.is_dir():
            continue
        name = p.name.strip().lower()
        if not name or name.startswith("."):
            continue
        if (p / "confirmation.html").is_file():
            out.append(name)
    return tuple(out)


AQUA_SERVICE_CHOICES: tuple[str, ...] = _services_from_env() or _services_from_html_dirs()


def normalize_aqua_service(code: str | None) -> str | None:
    s = (code or "").strip().lower()
    if not s:
        return None
    # Удалённые CH-сервисы GAG — не принимаем
    if s in {"ricardo_ch", "tutti_ch", "ricardo", "tutti", "ricardo.ch", "tutti.ch"}:
        return None
    if AQUA_SERVICE_CHOICES:
        return s if s in AQUA_SERVICE_CHOICES else None
    return None


def is_valid_aqua_service(code: str | None) -> bool:
    return normalize_aqua_service(code) is not None


def aqua_service_for_api(code: str | None) -> str:
    n = normalize_aqua_service(code)
    if not n:
        raise ValueError(f"Unknown service: {code!r}")
    return n


def aqua_service_for_html_dir(code: str | None) -> str:
    return normalize_aqua_service(code) or ""


def aqua_service_matches(cur: str | None, choice: str) -> bool:
    a = normalize_aqua_service(cur)
    b = normalize_aqua_service(choice)
    return bool(a and b and a == b)


def aqua_service_label(code: str | None) -> str:
    n = normalize_aqua_service(code) or (code or "").strip()
    return n or "—"


async def get_user_aqua_service(session, user: User) -> str:
    raw = (await get_user_setting(session, user, AQUA_SERVICE_KEY) or "").strip()
    normalized = normalize_aqua_service(raw)
    if normalized:
        return normalized
    default = normalize_aqua_service(AQUA_DEFAULT_SERVICE)
    if default:
        return default
    if AQUA_SERVICE_CHOICES:
        return AQUA_SERVICE_CHOICES[0]
    return ""


async def get_user_generate_domain(session, user: User) -> int | None:
    from services.gag_domains import get_user_gag_domain_mode, gag_api_domain_for_mode

    mode = await get_user_gag_domain_mode(session, user)
    return gag_api_domain_for_mode(mode)


def normalize_aqua_api_key(value: str | None) -> str:
    v = clean_secret(value)
    if not v:
        return ""
    low = v.lower()
    if low.startswith("apikey"):
        v = v[6:].lstrip(":").strip()
    elif low.startswith("bearer"):
        v = v[6:].lstrip(":").strip()
    return v


def get_global_aqua_team_key() -> str:
    """X-Team-Key глобально (Railway Variables) для всех пользователей."""
    raw = (
        os.getenv("GOO_TEAM_KEY")
        or os.getenv("EVOLEUM_TEAM_KEY")
        or os.getenv("X_TEAM_KEY")
        or os.getenv("TEAM_API_KEY")
        or os.getenv("GAG_TEAM_API_KEY")
        or os.getenv("AQUA_TEAM_API_KEY")
        or getattr(config, "GAG_TEAM_API_KEY", None)
        or getattr(config, "AQUA_TEAM_API_KEY", None)
        or ""
    )
    raw = str(raw).strip().strip('"').strip("'")
    return normalize_aqua_api_key(raw)


def get_team_name() -> str:
    return getattr(config, "TEAM_NAME", None) or TEAM_NAME or ""


def get_user_aqua_user_key(user: User) -> str:
    return normalize_aqua_api_key(getattr(user, "goo_user_api_key_aqua", None))


async def get_user_aqua_user_key_async(session, user: User) -> str:
    user_key = get_user_aqua_user_key(user)
    if user_key:
        return user_key
    raw = (await get_user_setting(session, user, AQUA_USER_API_KEY_SETTING) or "").strip()
    return normalize_aqua_api_key(raw)


async def set_user_aqua_user_key(session, user: User, value: str) -> None:
    key = normalize_aqua_api_key(value)
    user.goo_user_api_key_aqua = key or None
    await set_user_setting(session, user, AQUA_USER_API_KEY_SETTING, key)


async def get_user_aqua_api_keys_async(session, user: User) -> tuple[str, str]:
    user_key = await get_user_aqua_user_key_async(session, user)
    return user_key, ""


def get_user_aqua_api_keys(user: User) -> tuple[str, str]:
    return get_user_aqua_user_key(user), ""


def get_user_goo_profile_id(user: User) -> str:
    return (getattr(user, "goo_profile_id", None) or "").strip()


async def get_user_profile_title(session, user: User) -> str:
    return (await get_user_setting(session, user, AQUA_PROFILE_TITLE_KEY) or "").strip()


async def get_user_profile_buyer_name(session, user: User) -> str:
    return (await get_user_setting(session, user, AQUA_PROFILE_NAME_KEY) or "").strip()


async def get_user_profile_address(session, user: User) -> str:
    return (await get_user_setting(session, user, AQUA_PROFILE_ADDRESS_KEY) or "").strip()


async def user_profile_fields_complete(session, user: User) -> bool:
    return bool(
        await get_user_profile_title(session, user)
        and await get_user_profile_buyer_name(session, user)
        and await get_user_profile_address(session, user)
    )


async def get_user_aqua_profile_display(session, user: User) -> str:
    title = await get_user_profile_title(session, user)
    name = await get_user_profile_buyer_name(session, user)
    if title and name:
        return f"{title} · {name}"
    return title or name or get_user_goo_profile_id(user)


async def apply_aqua_profile_to_user(session, user: User, profile) -> None:
    from services.aqua_profiles import AquaProfile

    if not isinstance(profile, AquaProfile):
        raise TypeError("profile must be AquaProfile")
    user.goo_profile_id = profile.profile_id
    await set_user_setting(session, user, AQUA_PROFILE_TITLE_KEY, profile.title)
    await set_user_setting(session, user, AQUA_PROFILE_NAME_KEY, profile.full_name)
    await set_user_setting(session, user, AQUA_PROFILE_ADDRESS_KEY, profile.address)
