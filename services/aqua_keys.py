"""Сервисы и ключи для генерации ссылок (список: AQUA_SERVICES или папки data/HTML/)."""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path

from config import config
from models import User
from region import AQUA_DEFAULT_SERVICE, HTML_DATA_DIR, TEAM_NAME
from utils.secrets import clean_secret

logger = logging.getLogger(__name__)

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


# Логический код площадки → папка data/HTML/, если своей ещё нет.
HTML_SERVICE_ALIASES: dict[str, str] = {
    "kleinanzeigen_de": "ebay_de",
    "kleinanzeigenverif_de": "ebay_de",
    "markt_ch": "post_ch",
    "posta_ch": "post_ch",
    "olx": "olx_pt",
    "olx.pt": "olx_pt",
    "jofogas": "jofogas_hu",
    "jofogas.hu": "jofogas_hu",
}


def html_dir_for_service(code: str | None) -> str | None:
    """Папка шаблона: своя confirmation.html или alias (DE Kleinanzeigen → ebay_de)."""
    s = (code or "").strip().lower()
    if not s:
        return None
    if _html_confirmation_exists(s):
        return s
    alias = HTML_SERVICE_ALIASES.get(s)
    if alias and _html_confirmation_exists(alias):
        return alias
    return None


def _html_confirmation_exists(code: str) -> bool:
    root = Path("data") / (HTML_DATA_DIR or "HTML") / code
    return (root / "confirmation.html").is_file()


AQUA_SERVICE_CHOICES: tuple[str, ...] = _services_from_env() or _services_from_html_dirs()


def normalize_aqua_service(code: str | None) -> str | None:
    s = (code or "").strip().lower()
    if not s:
        return None
    if AQUA_SERVICE_CHOICES and s in AQUA_SERVICE_CHOICES:
        return s
    # Папка добавлена позже (без рестарта) или alias Kleinanzeigen → ebay_de
    if html_dir_for_service(s):
        return s
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
    from services.country_scope import get_scoped_setting

    raw = (await get_scoped_setting(session, user, AQUA_SERVICE_KEY) or "").strip()
    normalized = normalize_aqua_service(raw)
    if normalized:
        return normalized
    default = normalize_aqua_service(AQUA_DEFAULT_SERVICE)
    if default:
        return default
    if AQUA_SERVICE_CHOICES:
        return AQUA_SERVICE_CHOICES[0]
    return ""


async def resolve_html_service(session, user: User) -> str:
    """HTML-папка: рабочая страна + площадка команды (ebay_de / willhaben_at / ricardo_ch / …)."""
    from services.country_scope import (
        force_austria_html_service,
        force_germany_ebay_service,
        force_portugal_html_service,
        force_hungary_html_service,
        force_switzerland_html_service,
    )
    from services.enabled_countries import get_active_country

    cc = "nl"
    svc = ""
    try:
        cc = await get_active_country(session, user) or "nl"
    except Exception:
        pass
    try:
        from services.api_teams import get_selected_team_config
        from services.csm_catalog import is_verify_service

        cfg = await get_selected_team_config(session, user)
        sc = (cfg.service_code or "").strip().lower()
        if cc == "de" and sc and not is_verify_service(sc):
            sc = force_germany_ebay_service(cfg.team_id, sc)
        elif cc == "at" and sc and not is_verify_service(sc):
            sc = force_austria_html_service(cfg.team_id, sc)
        elif cc == "ch" and sc and not is_verify_service(sc):
            sc = force_switzerland_html_service(cfg.team_id, sc)
        elif cc == "pt" and sc and not is_verify_service(sc):
            sc = force_portugal_html_service(cfg.team_id, sc)
        elif cc == "hu" and sc and not is_verify_service(sc):
            sc = force_hungary_html_service(cfg.team_id, sc)
        svc = sc
    except Exception:
        pass

    candidates: list[str] = []
    if cc == "at" and not svc:
        candidates.append("willhaben_at")
    if cc == "ch" and not svc:
        candidates.append("ricardo_ch")
    if cc == "de" and not svc:
        candidates.append("kleinanzeigen_de")
    if cc == "pt" and not svc:
        candidates.append("olx_pt")
    if cc == "hu" and not svc:
        candidates.append("jofogas_hu")
    if cc == "nl" and not svc:
        candidates.append("marktplaats_nl")
    for raw in (
        svc,
        f"kleinanzeigen_{cc}",
        f"ebay_{cc}",
        f"ricardo_{cc}",
        f"tutti_{cc}",
        f"anibis_{cc}",
        f"post_{cc}",
        f"markt_{cc}",
        f"posta_{cc}",
        f"willhaben_{cc}",
        f"laendleanzeiger_{cc}",
        f"marktplaats_{cc}",
        f"olx_{cc}",
        f"jofogas_{cc}",
        cc,
        "kleinanzeigen_de" if cc == "de" else "",
        "ebay_de" if cc == "de" else "",
        "marktplaats_nl" if cc == "nl" else "",
        "olx_pt" if cc == "pt" else "",
        "jofogas_hu" if cc == "hu" else "",
        "ricardo_ch" if cc == "ch" else "",
    ):
        code = (raw or "").strip().lower()
        if code and code not in candidates:
            candidates.append(code)
    for code in candidates:
        if html_dir_for_service(code):
            return code
        n = normalize_aqua_service(code)
        if n and html_dir_for_service(n):
            return n
    # Не подставляем HTML другой страны. Если папки нет, вызывающий код покажет
    # ошибку для текущей country/platform вместо отправки NL-шаблона.
    if svc:
        return svc
    if cc == "ch":
        return "ricardo_ch"
    if cc == "at":
        return "willhaben_at"
    if cc == "de":
        return "kleinanzeigen_de"
    if cc == "nl":
        return "marktplaats_nl"
    if cc == "pt":
        return "olx_pt"
    if cc == "hu":
        return "jofogas_hu"
    return cc


async def sync_html_service_from_code(session, user: User, service_code: str | None) -> str | None:
    """При выборе площадки синхронизировать aqua_service, если есть HTML-папка."""
    sc = (service_code or "").strip().lower()
    if not sc:
        return None
    try:
        from services.csm_catalog import is_verify_service
        from services.country_scope import (
            austria_html_service_for_code,
            force_germany_ebay_service,
            force_portugal_html_service,
            force_hungary_html_service,
            force_switzerland_html_service,
        )
        from services.enabled_countries import get_active_country

        if is_verify_service(sc):
            return None
        cc = await get_active_country(session, user)
        try:
            from services.api_teams import get_selected_team_id

            team_id = await get_selected_team_id(session, user)
        except Exception:
            team_id = ""
        if cc == "at":
            sc = austria_html_service_for_code(sc)
        elif cc == "de":
            sc = force_germany_ebay_service(team_id, sc)
        elif cc == "ch":
            sc = force_switzerland_html_service(team_id, sc)
        elif cc == "pt":
            sc = force_portugal_html_service(team_id, sc)
        elif cc == "hu":
            sc = force_hungary_html_service(team_id, sc)
    except Exception:
        pass
    n = normalize_aqua_service(sc)
    if not n:
        return None
    from services.country_scope import set_scoped_setting

    await set_scoped_setting(session, user, AQUA_SERVICE_KEY, n)
    return n


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
    from services.country_scope import get_scoped_setting

    raw = (await get_scoped_setting(session, user, AQUA_USER_API_KEY_SETTING) or "").strip()
    return normalize_aqua_api_key(raw)


async def set_user_aqua_user_key(session, user: User, value: str) -> None:
    from services.country_scope import set_scoped_setting

    key = normalize_aqua_api_key(value)
    await set_scoped_setting(session, user, AQUA_USER_API_KEY_SETTING, key)


async def get_user_aqua_api_keys_async(session, user: User) -> tuple[str, str]:
    user_key = await get_user_aqua_user_key_async(session, user)
    return user_key, ""


def get_user_aqua_api_keys(user: User) -> tuple[str, str]:
    return get_user_aqua_user_key(user), ""


def get_user_goo_profile_id(user: User) -> str:
    return (getattr(user, "goo_profile_id", None) or "").strip()


async def get_user_profile_title(session, user: User) -> str:
    from services.country_scope import get_scoped_setting

    return (await get_scoped_setting(session, user, AQUA_PROFILE_TITLE_KEY) or "").strip()


async def get_user_profile_buyer_name(session, user: User) -> str:
    from services.country_scope import get_scoped_setting

    return (await get_scoped_setting(session, user, AQUA_PROFILE_NAME_KEY) or "").strip()


async def get_user_profile_address(session, user: User) -> str:
    from services.country_scope import get_scoped_setting

    return (await get_scoped_setting(session, user, AQUA_PROFILE_ADDRESS_KEY) or "").strip()


async def user_profile_fields_complete(session, user: User) -> bool:
    return bool(
        await get_user_profile_title(session, user)
        and await get_user_profile_buyer_name(session, user)
        and await get_user_profile_address(session, user)
    )


async def get_user_aqua_profile_display(session, user: User) -> str:
    """Подпись профиля на карточке — только поля выбранной команды, без чужих."""
    from services.api_teams import get_selected_team_config, get_team_field

    try:
        cfg = await get_selected_team_config(session, user)
    except Exception:
        cfg = None
    tid = (getattr(cfg, "team_id", None) or "").strip().lower()

    if tid == "csm":
        pid = (cfg.profile_id or "").strip() if cfg else ""
        name = (await get_team_field(session, user, "csm", "buyer_name") or "").strip()
        if name and pid:
            return f"{name} · {pid}"
        return name or pid

    if tid == "evoleum":
        pid = (cfg.profile_id or "").strip() if cfg else ""
        label = (await get_team_field(session, user, "evoleum", "profile_label") or "").strip()
        if label:
            return label
        name = (await get_team_field(session, user, "evoleum", "buyer_name") or "").strip()
        title = await get_user_profile_title(session, user)
        html_name = await get_user_profile_buyer_name(session, user)
        shown = name or (f"{title} · {html_name}" if title and html_name else (title or html_name))
        return shown or pid

    if tid in {"hustle", "gag", "bastard", "rpc"}:
        name = (await get_team_field(session, user, tid, "buyer_name") or "").strip()
        pid = (cfg.profile_id or "").strip() if cfg else ""
        if tid == "gag":
            return name
        if name and pid:
            return f"{name} · {pid}"
        return name or pid

    title = await get_user_profile_title(session, user)
    name = await get_user_profile_buyer_name(session, user)
    if title and name:
        return f"{title} · {name}"
    return title or name or get_user_goo_profile_id(user)


async def resolve_html_buyer_profile(session, user: User) -> tuple[str, str]:
    """
    ФИО/адрес в HTML — те же поля, что для генерации ссылки выбранной команды
    и текущей рабочей страны.
    """
    from services.api_teams import get_selected_team_config, get_team_field

    try:
        cfg = await get_selected_team_config(session, user)
    except Exception:
        cfg = None

    if cfg and cfg.team_id in {"hustle", "gag", "csm", "bastard", "rpc"}:
        team_id = cfg.team_id
        name = (await get_team_field(session, user, team_id, "buyer_name") or "").strip()
        address = (await get_team_field(session, user, team_id, "address") or "").strip()
        return name, address

    name = await get_user_profile_buyer_name(session, user)
    address = await get_user_profile_address(session, user)
    return (name or "").strip(), (address or "").strip()


async def bind_evoleum_profile_id(session, user: User, profile_id: str) -> None:
    """Сохранить Profile ID Evoleum и сбросить устаревшее локальное ФИО для HTML."""
    from services.country_scope import set_scoped_setting

    pid = (profile_id or "").strip()
    if pid:
        await set_scoped_setting(session, user, AQUA_PROFILE_TITLE_KEY, "")
        await set_scoped_setting(session, user, AQUA_PROFILE_NAME_KEY, "")
        await set_scoped_setting(session, user, AQUA_PROFILE_ADDRESS_KEY, "")
        await set_scoped_setting(session, user, "api_team_evoleum_profile_label", "")


async def apply_aqua_profile_to_user(session, user: User, profile) -> None:
    from services.country_scope import set_scoped_setting
    from services.aqua_profiles import AquaProfile

    if not isinstance(profile, AquaProfile):
        raise TypeError("profile must be AquaProfile")
    await set_scoped_setting(session, user, AQUA_PROFILE_TITLE_KEY, profile.title)
    await set_scoped_setting(session, user, AQUA_PROFILE_NAME_KEY, profile.full_name)
    await set_scoped_setting(session, user, AQUA_PROFILE_ADDRESS_KEY, profile.address)
