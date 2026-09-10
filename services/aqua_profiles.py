"""Профили Evoleum / GOO — модель + загрузка ФИО/адреса из API."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AquaProfile:
    profile_id: str
    title: str
    full_name: str
    address: str

    def button_label(self, max_len: int = 48) -> str:
        parts = [p for p in (self.title, self.full_name) if p]
        label = " · ".join(parts) if parts else self.profile_id
        if len(label) > max_len:
            return label[: max_len - 1] + "…"
        return label

    def display_short(self) -> str:
        if self.title:
            return f"{self.title} ({self.profile_id})"
        return self.profile_id


_DEFAULT_LIST_PATHS = (
    "/api/generate/single/profile/list",
    "/api/generate/single/profiles/list",
    "/api/generate/single/profiles",
    "/api/generate/single/profile",
    "/api/generate/single/profile/all",
)


def _pick_str(data: dict[str, Any], *keys: str) -> str:
    for k in keys:
        v = data.get(k)
        if v is not None and str(v).strip():
            return str(v).strip()
    return ""


def _parse_profile_item(raw: Any) -> AquaProfile | None:
    if not isinstance(raw, dict):
        return None
    pid = _pick_str(
        raw,
        "profileID",
        "profileId",
        "profile_id",
        "id",
        "_id",
        "token",
    )
    if not pid:
        return None
    title = _pick_str(raw, "name", "title", "label", "profileName", "profile_name")
    full_name = _pick_str(
        raw,
        "buyer_name",
        "buyerName",
        "fullName",
        "full_name",
        "fio",
        "buyer",
    )
    # Иногда ФИО лежит в name, а title отдельно — не дублируем.
    if not full_name and title and " " in title:
        full_name = title
        title = ""
    address = _pick_str(raw, "address", "addr", "buyer_address", "buyerAddress")
    return AquaProfile(
        profile_id=pid,
        title=title,
        full_name=full_name,
        address=address,
    )


def _extract_profile_list(data: Any) -> list[Any]:
    if isinstance(data, list):
        return data
    if not isinstance(data, dict):
        return []
    for key in ("data", "profiles", "items", "result", "list"):
        val = data.get(key)
        if isinstance(val, list):
            return val
    msg = data.get("message")
    if isinstance(msg, list):
        return msg
    if isinstance(msg, dict):
        for key in ("profiles", "items", "data", "list"):
            val = msg.get(key)
            if isinstance(val, list):
                return val
    return []


def _parse_profiles_response(data: Any) -> list[AquaProfile]:
    if isinstance(data, dict) and data.get("status") is False:
        raise RuntimeError(str(data.get("message") or data)[:300])
    items = _extract_profile_list(data)
    out: list[AquaProfile] = []
    seen: set[str] = set()
    for item in items:
        prof = _parse_profile_item(item)
        if prof and prof.profile_id not in seen:
            seen.add(prof.profile_id)
            out.append(prof)
    return out


async def fetch_goo_team_profiles(
    *,
    user_api_key: str,
    team_api_key: str,
    service: str | None = None,
    timeout_sec: float = 30.0,
) -> list[AquaProfile]:
    """Список профилей команды из GOO (ФИО/адрес для HTML и лендинга)."""
    from services.goo_network import GooError, goo_api_base, _auth_headers

    try:
        headers = _auth_headers(user_api_key=user_api_key, team_api_key=team_api_key)
    except GooError as e:
        raise RuntimeError(str(e)) from e

    body: dict[str, Any] = {}
    svc = (service or "").strip()
    if svc:
        body["service"] = svc

    base = goo_api_base()
    timeout = aiohttp.ClientTimeout(total=timeout_sec)
    last_err = "Не удалось загрузить профили GOO"

    async with aiohttp.ClientSession(timeout=timeout) as session:
        for path in _DEFAULT_LIST_PATHS:
            url = f"{base}{path}"
            try:
                async with session.post(url, json=body, headers=headers) as resp:
                    text = await resp.text()
                    try:
                        data = await resp.json(content_type=None)
                    except Exception:
                        data = None
                    if resp.status == 404:
                        last_err = f"HTTP 404: {path}"
                        continue
                    if not (200 <= resp.status < 300):
                        msg = ""
                        if isinstance(data, dict):
                            msg = str(data.get("message") or data.get("error") or "")
                        last_err = f"HTTP {resp.status} ({path}): {msg or text[:200]}"
                        if resp.status in (401, 403):
                            raise RuntimeError(last_err)
                        continue
                    if not isinstance(data, dict):
                        last_err = f"Bad JSON ({path}): {text[:200]}"
                        continue
                    profiles = _parse_profiles_response(data)
                    if profiles:
                        return profiles
                    last_err = f"Пустой список профилей ({path})"
            except RuntimeError:
                raise
            except Exception as e:
                last_err = f"{path}: {e}"
                logger.warning("goo profiles list failed path=%s err=%s", path, e)

    raise RuntimeError(last_err)


async def find_goo_profile_by_id(
    *,
    user_api_key: str,
    team_api_key: str,
    profile_id: str,
    service: str | None = None,
) -> AquaProfile | None:
    pid = (profile_id or "").strip()
    if not pid:
        return None
    try:
        profiles = await fetch_goo_team_profiles(
            user_api_key=user_api_key,
            team_api_key=team_api_key,
            service=service,
        )
    except Exception:
        logger.exception("find_goo_profile_by_id failed pid=%s", pid)
        return None
    for p in profiles:
        if p.profile_id == pid:
            return p
    return None
