"""GAG API — Швейцария: ricardo.ch, tutti.ch."""

from __future__ import annotations

import os

from config import config
from models import User
from region import AQUA_DEFAULT_SERVICE, TEAM_NAME
from services.user_settings import get_user_setting, set_user_setting
from utils.secrets import clean_secret

AQUA_SERVICE_KEY = "aqua_service"

AQUA_USER_API_KEY_SETTING = "aqua_user_api_key"

AQUA_PROFILE_TITLE_KEY = "aqua_profile_title"
AQUA_PROFILE_NAME_KEY = "aqua_profile_name"
AQUA_PROFILE_ADDRESS_KEY = "aqua_profile_address"

AQUA_GENERATE_DOMAIN_KEY = "aqua_generate_domain"

# domain в POST /generate (GAG API): 1 — личный, 2 — команда (как в старых ботах).
GENERATE_DOMAIN_CHOICES: tuple[tuple[str, str], ...] = (
    ("1", "Личный домен"),
    ("2", "Домен команды"),
)

AQUA_SERVICE_CHOICES = ("ricardo_ch", "tutti_ch")

_SERVICE_ALIASES: dict[str, str] = {
    "ricardo_ch": "ricardo_ch",
    "ricardo.ch": "ricardo_ch",
    "ricardo": "ricardo_ch",
    "tutti_ch": "tutti_ch",
    "tutti.ch": "tutti_ch",
    "tutti": "tutti_ch",
}


def normalize_aqua_service(code: str | None) -> str | None:
    s = (code or "").strip().lower()
    if not s:
        return None
    return _SERVICE_ALIASES.get(s)


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
    return {
        "ricardo_ch": "ricardo.ch",
        "tutti_ch": "tutti.ch",
    }.get(n, n or "—")


async def get_user_aqua_service(session, user: User) -> str:
    raw = (await get_user_setting(session, user, AQUA_SERVICE_KEY) or "").strip()
    normalized = normalize_aqua_service(raw)
    if normalized:
        return normalized
    return normalize_aqua_service(AQUA_DEFAULT_SERVICE) or AQUA_DEFAULT_SERVICE


def generate_domain_label(num: int | str | None) -> str:
    s = str(num or "").strip()
    for code, label in GENERATE_DOMAIN_CHOICES:
        if code == s:
            return label
    return f"domain {s}" if s else "—"


async def get_user_generate_domain(session, user: User) -> int:
    raw = (await get_user_setting(session, user, AQUA_GENERATE_DOMAIN_KEY) or "").strip()
    if raw.isdigit():
        n = int(raw)
        if 1 <= n <= 8:
            return n
    try:
        n = int(getattr(config, "GAG_GENERATE_DOMAIN", None) or 1)
    except (TypeError, ValueError):
        n = 1
    return max(1, min(8, n))


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
    """Ключ команды GAG — GAG_TEAM_API_KEY."""
    raw = (
        os.getenv("GAG_TEAM_API_KEY")
        or os.getenv("AQUA_TEAM_API_KEY")
        or getattr(config, "GAG_TEAM_API_KEY", None)
        or getattr(config, "AQUA_TEAM_API_KEY", None)
        or ""
    )
    raw = str(raw).strip().strip('"').strip("'")
    return normalize_aqua_api_key(raw)


def get_team_name() -> str:
    return getattr(config, "TEAM_NAME", None) or TEAM_NAME


def get_user_aqua_user_key(user: User) -> str:
    return normalize_aqua_api_key(getattr(user, "goo_user_api_key_aqua", None))


async def get_user_aqua_user_key_async(session, user: User) -> str:
    user_key = get_user_aqua_user_key(user)
    if not user_key:
        user_key = normalize_aqua_api_key(
            await get_user_setting(session, user, AQUA_USER_API_KEY_SETTING) or ""
        )
    return user_key


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
