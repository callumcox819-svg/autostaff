"""Команды API: CSM / Evoleum / Hustle Castle — выбор и поля для генерации."""

from __future__ import annotations

from dataclasses import dataclass

from models import User
from services.aqua_keys import get_global_aqua_team_key
from utils.secrets import clean_secret

SELECTED_TEAM_KEY = "api_team_selected"

# id → отображаемое имя
API_TEAMS: tuple[tuple[str, str], ...] = (
    ("csm", "CSM"),
    ("evoleum", "Evoleum"),
    ("hustle", "Hustle Castle"),
    ("gag", "GAG"),
)

_TEAM_IDS = {tid for tid, _ in API_TEAMS}

# id, label, premium emoji key
LINK_TYPES: tuple[tuple[str, str, str], ...] = (
    ("lk", "LK", "link"),
    ("card", "Card", "presets"),
    ("other", "Другое", "puzzle"),
)
_LINK_TYPE_IDS = {t for t, _, _ in LINK_TYPES}

GAG_LINK_TYPES: tuple[tuple[str, str, str], ...] = (
    ("lk", "LK — /get/", "link"),
    ("1", "Версия 1 — /buy/", "presets"),
    ("2", "Версия 2 — /", "puzzle"),
)
_GAG_LINK_TYPE_IDS = {t for t, _, _ in GAG_LINK_TYPES}


@dataclass(frozen=True)
class ApiTeamConfig:
    team_id: str
    label: str
    api_key: str
    team_key: str  # всегда из Railway env
    service_code: str
    profile_id: str
    link_type: str  # lk | card | other


def team_label(team_id: str) -> str:
    for tid, label in API_TEAMS:
        if tid == team_id:
            return label
    return team_id or "—"


def link_types_for_team(team_id: str) -> tuple[tuple[str, str, str], ...]:
    return GAG_LINK_TYPES if (team_id or "").strip().lower() == "gag" else LINK_TYPES


def link_type_label(link_type: str, *, team_id: str = "") -> str:
    for tid, label, _ in link_types_for_team(team_id):
        if tid == link_type:
            return label
    return link_type or "—"


def normalize_team_id(raw: str | None) -> str | None:
    s = (raw or "").strip().lower()
    if s in _TEAM_IDS:
        return s
    if s in {"evollum", "evoleum_nl", "evolium"}:
        return "evoleum"
    if s in {"hustle_castle", "hustlecastle", "incore", "inc-core", "inc_core", "inccore"}:
        return "hustle"
    if s in {"gag_bot", "aqua", "generate"}:
        return "gag"
    return None


def _sk(team_id: str, field: str) -> str:
    return f"api_team_{team_id}_{field}"


def default_service_for_team(team_id: str) -> str:
    if team_id == "evoleum":
        return "marktplaats_nl"
    if team_id == "csm":
        return "marktplaats_nl"
    if team_id == "hustle":
        return "kleinanzeigen_de"
    if team_id == "gag":
        return "ricardo_ch"
    return ""


def default_type_for_team(team_id: str) -> str:
    return "lk"


async def get_selected_team_id(session, user: User) -> str:
    from services.country_scope import get_scoped_setting

    raw = await get_scoped_setting(session, user, SELECTED_TEAM_KEY)
    tid = normalize_team_id(raw)
    if tid:
        return tid
    return "evoleum"


async def set_selected_team_id(session, user: User, team_id: str) -> str:
    tid = normalize_team_id(team_id)
    if not tid:
        raise ValueError(f"Unknown team: {team_id!r}")
    from services.country_scope import set_scoped_setting

    await set_scoped_setting(session, user, SELECTED_TEAM_KEY, tid)
    return tid


async def get_team_field(session, user: User, team_id: str, field: str) -> str:
    tid = normalize_team_id(team_id) or ""
    if not tid:
        return ""
    from services.country_scope import get_scoped_setting

    val = (await get_scoped_setting(session, user, _sk(tid, field)) or "").strip()
    if val:
        return val
    if field == "service_code":
        return default_service_for_team(tid)
    if field == "link_type":
        return default_type_for_team(tid)
    return ""


async def set_team_field(session, user: User, team_id: str, field: str, value: str) -> None:
    tid = normalize_team_id(team_id)
    if not tid:
        raise ValueError(f"Unknown team: {team_id!r}")
    if field == "team_key":
        raise ValueError("Team-ключ задаётся только на сервере")
    if tid == "gag" and field == "service_code":
        raise ValueError("GAG работает только с Ricardo Switzerland (ricardo_ch)")
    if field == "api_key":
        value = clean_secret(value)
    elif field == "link_type":
        v = (value or "").strip().lower()
        allowed = _GAG_LINK_TYPE_IDS if tid == "gag" else _LINK_TYPE_IDS
        if v not in allowed:
            expected = "lk, 1 или 2" if tid == "gag" else "lk, card или other"
            raise ValueError(f"Тип: {expected}")
        value = v
    elif field == "profile_id":
        value = clean_secret(value)
    else:
        value = (value or "").strip()
    from services.country_scope import set_scoped_setting

    await set_scoped_setting(session, user, _sk(tid, field), value)
    if tid == "evoleum" and field == "profile_id":
        from services.aqua_keys import bind_evoleum_profile_id

        await bind_evoleum_profile_id(session, user, value)


def _team_key_for(team_id: str) -> str:
    if team_id == "hustle":
        from services.hustle_network import hustle_team_key

        return hustle_team_key()
    if team_id == "gag":
        # GAG использует личный apikey; инфраструктурный URL скрыт от пользователя.
        return ""
    return get_global_aqua_team_key()


async def get_team_config(session, user: User, team_id: str) -> ApiTeamConfig:
    tid = normalize_team_id(team_id) or (team_id or "").strip().lower()
    api_key = await get_team_field(session, user, tid, "api_key")
    service_code = await get_team_field(session, user, tid, "service_code")
    profile_id = await get_team_field(session, user, tid, "profile_id")
    if tid == "gag" and not (api_key or "").strip():
        from services.aqua_keys import get_user_aqua_user_key_async

        api_key = (await get_user_aqua_user_key_async(session, user) or "").strip()
    if tid == "gag":
        service_code = "ricardo_ch"
    link_type = await get_team_field(session, user, tid, "link_type") or "lk"
    if tid == "gag" and link_type not in _GAG_LINK_TYPE_IDS:
        link_type = "lk"
    return ApiTeamConfig(
        team_id=tid,
        label=team_label(tid),
        api_key=api_key,
        team_key=_team_key_for(tid),
        service_code=service_code,
        profile_id=profile_id,
        link_type=link_type,
    )


async def get_selected_team_config(session, user: User) -> ApiTeamConfig:
    tid = await get_selected_team_id(session, user)
    return await get_team_config(session, user, tid)
