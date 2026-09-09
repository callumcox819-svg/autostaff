"""GOO.NETWORK generate API — https://docs.goo.network/core/generaciya-dannykh/generaciya-ssylki"""

from __future__ import annotations

import logging
import os
import re
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)

def goo_api_base() -> str:
    # Evoleum / legacy GOO: как в finland-bot — api-old.goo.network
    # (api.goo.network на этих же ключах отвечает 401 invalid credentials).
    return (
        os.getenv("GOO_API_BASE")
        or os.getenv("EVOLEUM_API_BASE")
        or "https://api-old.goo.network"
    ).strip().rstrip("/")


# backward-compat for imports/tests
GOO_API_BASE = goo_api_base()


class GooError(Exception):
    pass


def _auth_headers(*, user_api_key: str, team_api_key: str = "") -> dict[str, str]:
    from urllib.parse import urlparse

    user = (user_api_key or "").strip()
    team = (team_api_key or "").strip()
    if not user:
        raise GooError("Не задан API-ключ")
    if not team:
        raise GooError("Не задан Team-ключ на сервере")
    host = urlparse(goo_api_base()).hostname or "api-old.goo.network"
    return {
        "Authorization": f"Apikey {user}",
        "X-Team-Key": team,
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Host": host,
    }


def _extract_link(data: dict[str, Any]) -> str:
    if not isinstance(data, dict):
        raise GooError(f"Bad response: {data!r}")
    if data.get("status") is False or data.get("statusCode") is False:
        raise GooError(str(data.get("message") or data)[:400])
    msg = data.get("message")
    if isinstance(msg, str) and msg.strip().lower().startswith(("http://", "https://")):
        return msg.strip()
    for key in ("url", "link", "href"):
        val = data.get(key)
        if isinstance(val, str) and val.strip().lower().startswith(("http://", "https://")):
            return val.strip()
    raise GooError(f"No link in response: {str(data)[:300]}")


async def _post_json(path: str, body: dict[str, Any], *, headers: dict[str, str], timeout_sec: float = 45.0) -> dict[str, Any]:
    base = goo_api_base()
    url = f"{base}{path}"
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
                    detail = (msg or text[:300]).strip()
                    if resp.status == 401:
                        raise GooError(
                            "invalid credentials — проверь личный API-ключ Evoleum "
                            "(должен быть от той же команды, что и GOO_TEAM_KEY на сервере). "
                            f"Ответ API: {detail[:200]}"
                        )
                    raise GooError(f"HTTP {resp.status}: {detail}")
                if not isinstance(data, dict):
                    raise GooError(f"Bad JSON: {text[:300]}")
                return data
    except aiohttp.ClientError as e:
        raise GooError(f"Сеть ({url}): {e}") from e


def price_to_api_number(price: str | float | int | None) -> float:
    """Число для body.price (GOO требует number, не строку)."""
    if price is None:
        raise GooError("Нет цены")
    if isinstance(price, bool):
        raise GooError(f"Некорректная цена: {price!r}")
    if isinstance(price, (int, float)):
        n = float(price)
        if n < 0:
            raise GooError("Некорректная цена")
        return n
    raw = str(price).strip()
    if not raw:
        raise GooError("Нет цены")
    cleaned = re.sub(r"[^\d.,\-]", "", raw)
    if not cleaned or cleaned in {".", ",", "-", "-.", "-,"}:
        raise GooError(f"Не удалось разобрать цену: {price!r}")
    if "," in cleaned and "." in cleaned:
        # 1.250,50 (EU) vs 1,250.50 (US) — последний разделитель = дробная часть
        if cleaned.rfind(",") > cleaned.rfind("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        cleaned = cleaned.replace(",", ".")
    m = re.search(r"-?\d+(?:\.\d+)?", cleaned)
    if not m:
        raise GooError(f"Не удалось разобрать цену: {price!r}")
    n = float(m.group(0))
    if n < 0:
        raise GooError("Некорректная цена")
    return n


async def goo_generate_parse(
    *,
    user_api_key: str,
    team_api_key: str = "",
    service: str,
    listing_url: str,
    profile_id: str,
    balance_checker: bool = False,
    timeout_sec: float = 45.0,
) -> str:
    """POST /api/generate/single/parse"""
    svc = (service or "").strip()
    url = (listing_url or "").strip()
    pid = (profile_id or "").strip()
    if not svc:
        raise GooError("Не задан код сервиса")
    if not url.lower().startswith(("http://", "https://")):
        raise GooError("Нужна ссылка на объявление (parse)")
    if not pid:
        raise GooError("Не задан Profile ID")
    headers = _auth_headers(user_api_key=user_api_key, team_api_key=team_api_key)
    body = {
        "service": svc,
        "url": url,
        "isNeedBalanceChecker": bool(balance_checker),
        "profileID": pid,
    }
    data = await _post_json("/api/generate/single/parse", body, headers=headers, timeout_sec=timeout_sec)
    link = _extract_link(data)
    logger.info("goo parse ok service=%s", svc)
    return link


async def goo_generate_no_parse(
    *,
    user_api_key: str,
    team_api_key: str = "",
    service: str,
    name: str,
    price: str | float | int,
    profile_id: str,
    image: str | None = None,
    balance_checker: bool = False,
    timeout_sec: float = 45.0,
) -> str:
    """POST /api/generate/single/no-parse"""
    svc = (service or "").strip()
    title = (name or "").strip()
    pid = (profile_id or "").strip()
    if not svc:
        raise GooError("Не задан код сервиса")
    if not title:
        raise GooError("Нет названия товара")
    if not pid:
        raise GooError("Не задан Profile ID")
    headers = _auth_headers(user_api_key=user_api_key, team_api_key=team_api_key)
    body: dict[str, Any] = {
        "service": svc,
        "name": title,
        "price": price_to_api_number(price),
        "profileID": pid,
        "isNeedBalanceChecker": bool(balance_checker),
        "image": (image or "").strip() or "",
    }
    data = await _post_json("/api/generate/single/no-parse", body, headers=headers, timeout_sec=timeout_sec)
    link = _extract_link(data)
    logger.info("goo no-parse ok service=%s", svc)
    return link
