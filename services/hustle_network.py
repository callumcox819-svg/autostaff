"""Hustle Castle / INC-CORE generate API.

https://docs.inc-core.com/api/docs
Base: https://traff.inc-core.com
Auth: Authorization Bearer + X-Team-Key
Интервал ≥ 1 с между запросами (как в доке).
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any

import aiohttp

from services.goo_network import GooError, price_to_api_number
from services.hustle_catalog import EBAY_DE_CUSTOM, hustle_generate_mode

logger = logging.getLogger(__name__)

HUSTLE_API_BASE_DEFAULT = "https://traff.inc-core.com"

_RATE_LOCK = asyncio.Lock()
_LAST_REQUEST_MONO = 0.0
_MIN_INTERVAL_SEC = 1.05


class HustleError(Exception):
    pass


def hustle_api_base() -> str:
    return (
        os.getenv("HUSTLE_API_BASE")
        or os.getenv("INC_CORE_API_BASE")
        or HUSTLE_API_BASE_DEFAULT
    ).strip().rstrip("/")


def hustle_team_key() -> str:
    raw = (
        os.getenv("HUSTLE_TEAM_KEY")
        or os.getenv("INC_CORE_TEAM_KEY")
        or os.getenv("INCORE_TEAM_KEY")
        or ""
    )
    return str(raw).strip().strip('"').strip("'")


def bastard_team_key() -> str:
    raw = (
        os.getenv("BASTARD_TEAM_KEY")
        or os.getenv("INC_CORE_TEAM_KEY")
        or os.getenv("INCORE_TEAM_KEY")
        or os.getenv("HUSTLE_TEAM_KEY")
        or ""
    )
    return str(raw).strip().strip('"').strip("'")


def _auth_headers(*, api_key: str, team_key: str) -> dict[str, str]:
    user = (api_key or "").strip()
    team = (team_key or "").strip()
    if not user:
        raise HustleError("Не задан API-ключ Hustle Castle")
    if not team:
        raise HustleError("Не задан Team-ключ Hustle Castle на сервере (HUSTLE_TEAM_KEY)")
    return {
        "Authorization": f"Bearer {user}",
        "X-Team-Key": team,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _price_number(price: str | float | int | None) -> float:
    try:
        return price_to_api_number(price)
    except GooError as e:
        raise HustleError(str(e)) from e


def extract_hustle_link(data: dict[str, Any], *, link_type: str = "lk") -> str:
    if not isinstance(data, dict):
        raise HustleError(f"Bad response: {data!r}")
    if data.get("status") is False:
        raise HustleError(str(data.get("message") or data.get("error") or data)[:400])
    lt = (link_type or "lk").strip().lower()
    preferred: tuple[str, ...]
    if lt == "card":
        preferred = ("Link_shortener", "Link_multi", "Link", "link", "url")
    elif lt == "other":
        preferred = ("Link_multi", "Link_shortener", "Link", "link", "url")
    else:
        preferred = ("Link", "link", "url", "Link_shortener", "Link_multi")
    for key in preferred:
        val = data.get(key)
        if isinstance(val, str) and val.strip().lower().startswith(("http://", "https://")):
            return val.strip()
    raise HustleError(f"No link in response: {str(data)[:300]}")


async def _wait_rate_limit() -> None:
    global _LAST_REQUEST_MONO
    async with _RATE_LOCK:
        now = time.monotonic()
        wait = _MIN_INTERVAL_SEC - (now - _LAST_REQUEST_MONO)
        if wait > 0:
            await asyncio.sleep(wait)
        _LAST_REQUEST_MONO = time.monotonic()


async def _post_json(
    path: str,
    body: dict[str, Any],
    *,
    api_key: str,
    team_key: str,
    timeout_sec: float = 45.0,
) -> dict[str, Any]:
    await _wait_rate_limit()
    base = hustle_api_base()
    url = f"{base}{path}"
    headers = _auth_headers(api_key=api_key, team_key=team_key)
    timeout = aiohttp.ClientTimeout(total=timeout_sec)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, json=body, headers=headers) as resp:
                text = await resp.text()
                try:
                    data = await resp.json(content_type=None)
                except Exception:
                    data = None
                if not (200 <= resp.status < 300):
                    msg = ""
                    if isinstance(data, dict):
                        msg = str(data.get("message") or data.get("error") or "")
                    raise HustleError(f"HTTP {resp.status}: {msg or text[:300]}")
                if not isinstance(data, dict):
                    raise HustleError(f"Bad JSON: {text[:300]}")
                return data
    except aiohttp.ClientError as e:
        raise HustleError(f"Сеть ({url}): {e}") from e


def _listing_for_fast(listing_url: str) -> str:
    raw = (listing_url or "").strip()
    if raw.lower().startswith("https://"):
        return raw[8:]
    if raw.lower().startswith("http://"):
        return raw[7:]
    return raw


async def hustle_generate_fast(
    *,
    api_key: str,
    team_key: str,
    service: str,
    listing_url: str,
    profile_id: str,
    link_type: str = "lk",
) -> str:
    """POST /api/order/generate/fast — сервисы с меткой FAST."""
    svc = (service or "").strip()
    pid = (profile_id or "").strip()
    link_at = _listing_for_fast(listing_url)
    if not svc:
        raise HustleError("Не задан код сервиса")
    if not link_at:
        raise HustleError("Нужна ссылка на объявление (fast)")
    if not pid:
        raise HustleError("Не задан Profile ID")
    data = await _post_json(
        "/api/order/generate/fast",
        {"service": svc, "linkAt": link_at, "profileId": pid},
        api_key=api_key,
        team_key=team_key,
    )
    link = extract_hustle_link(data, link_type=link_type)
    logger.info("hustle fast ok service=%s", svc)
    return link


async def hustle_generate_lonely(
    *,
    api_key: str,
    team_key: str,
    service: str,
    name: str,
    price: str | float | int,
    user: str,
    address: str,
    photo: str,
    link_type: str = "lk",
) -> str:
    """POST /api/order/generate/lonely"""
    svc = (service or "").strip()
    title = (name or "").strip()
    buyer = (user or "").strip()
    addr = (address or "").strip()
    img = (photo or "").strip()
    if not svc:
        raise HustleError("Не задан код сервиса")
    if not title:
        raise HustleError("Нет названия объявления")
    if not buyer:
        raise HustleError("Не задано ФИО (Hustle Castle → ФИО)")
    if not addr:
        raise HustleError("Не задан адрес (Hustle Castle → Адрес)")
    if not img:
        raise HustleError("Нет фото объявления")
    body = {
        "service": svc,
        "name": title,
        "price": _price_number(price),
        "user": buyer,
        "address": addr,
        "photo": img,
    }
    data = await _post_json(
        "/api/order/generate/lonely",
        body,
        api_key=api_key,
        team_key=team_key,
    )
    link = extract_hustle_link(data, link_type=link_type)
    logger.info("hustle lonely ok service=%s", svc)
    return link


async def hustle_generate_custom(
    *,
    api_key: str,
    team_key: str,
    name: str,
    price: str | float | int,
    user: str,
    address: str,
    photo: str,
    platform: dict[str, str] | None = None,
    link_type: str = "lk",
) -> str:
    """POST /api/order/generate/custom — eBay DE и другие кастомные площадки."""
    plat = dict(platform or EBAY_DE_CUSTOM)
    title = (name or "").strip()
    buyer = (user or "").strip()
    addr = (address or "").strip()
    img = (photo or "").strip()
    if not title:
        raise HustleError("Нет названия объявления")
    if not buyer:
        raise HustleError("Не задано ФИО (Hustle Castle → ФИО)")
    if not addr:
        raise HustleError("Не задан адрес (Hustle Castle → Адрес)")
    if not img:
        raise HustleError("Нет фото объявления")
    body = {
        **plat,
        "name": title,
        "price": _price_number(price),
        "user": buyer,
        "address": addr,
        "photo": img,
    }
    data = await _post_json(
        "/api/order/generate/custom",
        body,
        api_key=api_key,
        team_key=team_key,
    )
    link = extract_hustle_link(data, link_type=link_type)
    logger.info("hustle custom ok service=%s", plat.get("service"))
    return link


def hustle_mode_for_service(service_code: str | None) -> str:
    return hustle_generate_mode(service_code)
