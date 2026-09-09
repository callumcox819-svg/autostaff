"""Команды API: CSM / Evoleum — выбор и поля для генерации."""

from __future__ import annotations

from dataclasses import dataclass

from models import User
from services.aqua_keys import get_global_aqua_team_key
from services.user_settings import get_user_setting, set_user_setting
from utils.secrets import clean_secret

SELECTED_TEAM_KEY = "api_team_selected"

# id → отображаемое имя
API_TEAMS: tuple[tuple[str, str], ...] = (
    ("csm", "CSM"),
    ("evoleum", "Evoleum"),
)

_TEAM_IDS = {tid for tid, _ in API_TEAMS}

# id, label, premium emoji key
LINK_TYPES: tuple[tuple[str, str, str], ...] = (
    ("lk", "LK", "link"),
    ("card", "Card", "presets"),
    ("other", "Другое", "puzzle"),
)
_LINK_TYPE_IDS = {t for t, _, _ in LINK_TYPES}


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


def link_type_label(link_type: str) -> str:
    for tid, label, _ in LINK_TYPES:
        if tid == link_type:
            return label
    return link_type or "—"


def normalize_team_id(raw: str | None) -> str | None:
    s = (raw or "").strip().lower()
    if s in _TEAM_IDS:
        return s
    if s in {"evollum", "evoleum_nl", "evolium"}:
        return "evoleum"
    return None


def _sk(team_id: str, field: str) -> str:
    return f"api_team_{team_id}_{field}"


def default_service_for_team(team_id: str) -> str:
    if team_id == "evoleum":
        return "marktplaats_nl"
    return ""


def default_type_for_team(team_id: str) -> str:
    return "lk"


async def get_selected_team_id(session, user: User) -> str:
    raw = await get_user_setting(session, user, SELECTED_TEAM_KEY)
    tid = normalize_team_id(raw)
    if tid:
        return tid
    return "evoleum"


async def set_selected_team_id(session, user: User, team_id: str) -> str:
    tid = normalize_team_id(team_id)
    if not tid:
        raise ValueError(f"Unknown team: {team_id!r}")
    await set_user_setting(session, user, SELECTED_TEAM_KEY, tid)
    return tid


async def get_team_field(session, user: User, team_id: str, field: str) -> str:
    tid = normalize_team_id(team_id) or ""
    if not tid:
        return ""
    val = (await get_user_setting(session, user, _sk(tid, field)) or "").strip()
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
        raise ValueError("Team-ключ задаётся глобально на сервере (Railway Variables)")
    if field == "api_key":
        value = clean_secret(value)
    elif field == "link_type":
        v = (value or "").strip().lower()
        if v not in _LINK_TYPE_IDS:
            raise ValueError("Тип: lk, card или other")
        value = v
    else:
        value = (value or "").strip()
    await set_user_setting(session, user, _sk(tid, field), value)


async def get_team_config(session, user: User, team_id: str) -> ApiTeamConfig:
    tid = normalize_team_id(team_id) or (team_id or "").strip().lower()
    return ApiTeamConfig(
        team_id=tid,
        label=team_label(tid),
        api_key=await get_team_field(session, user, tid, "api_key"),
        team_key=get_global_aqua_team_key(),
        service_code=await get_team_field(session, user, tid, "service_code"),
        profile_id=await get_team_field(session, user, tid, "profile_id"),
        link_type=await get_team_field(session, user, tid, "link_type") or "lk",
    )


async def get_selected_team_config(session, user: User) -> ApiTeamConfig:
    tid = await get_selected_team_id(session, user)
    return await get_team_config(session, user, tid)
