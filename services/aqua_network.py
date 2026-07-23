"""GAG / APEX API — генерация ссылок (Швейцария)."""

from __future__ import annotations

import logging
import re
from typing import Any

import aiohttp

from config import config
from services.aqua_keys import normalize_aqua_api_key

logger = logging.getLogger(__name__)

_DEFAULT_API_BASES = (
    "https://traffic.withhatetoapi.cc",
    "https://domainforapi.com",
)


class AquaError(Exception):
    pass


def _api_bases() -> list[str]:
    custom = (getattr(config, "GAG_API_BASE", None) or "").strip().rstrip("/")
    if custom:
        return [custom] + [b for b in _DEFAULT_API_BASES if b != custom]
    return list(_DEFAULT_API_BASES)


def _auth_header(user_api_key: str) -> str:
    key = normalize_aqua_api_key(user_api_key)
    if not key:
        return "Bearer "
    return f"Bearer {key}"


def _is_auth_error(exc: AquaError) -> bool:
    s = str(exc).lower()
    return "http 401" in s or "http 403" in s or "forbidden" in s


def price_to_api_number(price: str | float | int | None) -> float:
    """Число для поля price в APEX API."""
    if price is None:
        raise AquaError("Нет цены")
    if isinstance(price, (int, float)):
        n = float(price)
        if n < 0:
            raise AquaError("Некорректная цена")
        return n
    raw = str(price).strip().replace(",", ".")
    m = re.search(r"([\d.]+)", raw)
    if not m:
        raise AquaError(f"Не удалось разобрать цену: {price!r}")
    n = float(m.group(1))
    if n < 0:
        raise AquaError("Некорректная цена")
    return n


def _extract_link(data: dict[str, Any]) -> str:
    details = data.get("details")
    if isinstance(details, dict):
        short = details.get("short")
        if isinstance(short, dict):
            url = (short.get("url") or "").strip()
            if url:
                return url
        link = (details.get("link") or "").strip()
        if link:
            return link
    for key in ("link", "url", "message"):
        val = (data.get(key) or "").strip()
        if val.lower().startswith(("http://", "https://")):
            return val
    raise AquaError(f"No link in response: {str(data)[:300]}")


def _auth_error_message(status: int, msg: str) -> str:
    return (
        f"HTTP {status}: {msg or 'invalid credentials'}\n\n"
        "Проверь: личный ключ в ⚙️→🔑 («Ваш токен»), "
        "на сервере — GAG_TEAM_API_KEY («Токен команды»). "
        "Оба из панели GAG."
    )


async def _request_json(
    method: str,
    path: str,
    *,
    user_api_key: str,
    team_api_key: str,
    body: dict[str, Any] | None = None,
    timeout_sec: float = 30.0,
) -> dict[str, Any]:
    user_key = normalize_aqua_api_key(user_api_key)
    team_key = normalize_aqua_api_key(team_api_key)
    if not user_key:
        raise AquaError("Не задан личный API key")
    if not team_key:
        raise AquaError("Не задан Team API key (GAG_TEAM_API_KEY)")

    headers = {
        "Authorization": _auth_header(user_key),
        "X-Team-Key": team_key,
        "Content-Type": "application/json",
    }
    timeout = aiohttp.ClientTimeout(total=timeout_sec)
    last_err: AquaError | None = None

    async with aiohttp.ClientSession(timeout=timeout) as session:
        for base in _api_bases():
            url = f"{base}{path}"
            try:
                async with session.request(method, url, json=body, headers=headers) as resp:
                    text = await resp.text()
                    try:
                        data = await resp.json(content_type=None)
                    except Exception:
                        data = None
                    if not (200 <= resp.status < 300):
                        msg = ""
                        if isinstance(data, dict):
                            msg = str(data.get("message") or data.get("error") or "")
                        err = AquaError(f"HTTP {resp.status}: {msg or text[:300]}")
                        if resp.status in (401, 403):
                            logger.warning(
                                "GAG auth failed %s %s (user=%s… team=%s…)",
                                resp.status,
                                path,
                                user_key[:8],
                                team_key[:8],
                            )
                            raise AquaError(_auth_error_message(resp.status, msg)) from err
                        last_err = err
                        continue
                    if not isinstance(data, dict):
                        last_err = AquaError(f"Bad JSON: {text[:300]}")
                        continue
                    if data.get("success") is False:
                        last_err = AquaError(str(data.get("message") or data)[:300])
                        continue
                    return data
            except aiohttp.ClientError as e:
                last_err = AquaError(f"Сеть ({base}): {e}")
                continue

    raise last_err or AquaError("Не удалось выполнить запрос к API GAG")


async def verify_gag_auth(
    *,
    user_api_key: str,
    team_api_key: str,
    timeout_sec: float = 15.0,
) -> bool:
    """GET /api/hi — проверка личного и командного токена."""
    data = await _request_json(
        "GET",
        "/api/hi",
        user_api_key=user_api_key,
        team_api_key=team_api_key,
        timeout_sec=timeout_sec,
    )
    if data.get("success") is True:
        return True
    raise AquaError(str(data.get("message") or "Аутентификация не прошла")[:300])


async def _post_generate(
    path: str,
    *,
    user_api_key: str,
    team_api_key: str,
    body: dict[str, Any],
    timeout_sec: float = 30.0,
) -> str:
    data = await _request_json(
        "POST",
        path,
        user_api_key=user_api_key,
        team_api_key=team_api_key,
        body=body,
        timeout_sec=timeout_sec,
    )
    return _extract_link(data)


async def generate_aqua_link_parse(
    *,
    user_api_key: str,
    team_api_key: str,
    service: str,
    listing_url: str,
    buyer_name: str,
    address: str,
    balance_checker: bool = False,
    timeout_sec: float = 30.0,
) -> str:
    """POST /api/order/generate/lonely/parser — ссылка из URL объявления."""
    listing = (listing_url or "").strip()
    if not listing:
        raise AquaError("Нет URL объявления")
    buyer = (buyer_name or "").strip()
    addr = (address or "").strip()
    if not buyer:
        raise AquaError("Не задано имя получателя (профиль)")
    if not addr:
        raise AquaError("Не задан адрес доставки (профиль)")
    body: dict[str, Any] = {
        "service": service,
        "link": listing,
        "user": buyer,
        "address": addr,
        "checker_balance": bool(balance_checker),
    }
    return await _post_generate(
        "/api/order/generate/lonely/parser",
        user_api_key=user_api_key,
        team_api_key=team_api_key,
        body=body,
        timeout_sec=timeout_sec,
    )


async def generate_aqua_link_no_parse(
    *,
    user_api_key: str,
    team_api_key: str,
    service: str,
    name: str,
    price: str | float | int,
    buyer_name: str,
    address: str,
    image: str | None = None,
    balance_checker: bool = False,
    timeout_sec: float = 30.0,
) -> str:
    """POST /api/order/generate/lonely — ссылка по названию/цене/фото."""
    title = (name or "").strip()
    if not title:
        raise AquaError("Нет названия товара")
    buyer = (buyer_name or "").strip()
    addr = (address or "").strip()
    if not buyer:
        raise AquaError("Не задано имя получателя (профиль)")
    if not addr:
        raise AquaError("Не задан адрес доставки (профиль)")
    body: dict[str, Any] = {
        "service": service,
        "name": title,
        "price": price_to_api_number(price),
        "user": buyer,
        "address": addr,
        "checker_balance": bool(balance_checker),
    }
    img = (image or "").strip()
    if not img.lower().startswith(("http://", "https://")):
        default = (getattr(config, "AQUA_DEFAULT_IMAGE_URL", None) or "").strip()
        if default.lower().startswith(("http://", "https://")):
            img = default
    if img.lower().startswith(("http://", "https://")):
        body["photo"] = img
    return await _post_generate(
        "/api/order/generate/lonely",
        user_api_key=user_api_key,
        team_api_key=team_api_key,
        body=body,
        timeout_sec=timeout_sec,
    )


async def generate_aqua_link(
    *,
    user_api_key: str,
    team_api_key: str,
    service: str,
    buyer_name: str,
    address: str,
    listing_url: str | None = None,
    name: str | None = None,
    price: str | float | int | None = None,
    image: str | None = None,
    balance_checker: bool = False,
    prefer_parse: bool = True,
    timeout_sec: float = 30.0,
) -> str:
    """С парсером, если есть URL объявления; иначе lonely."""
    if prefer_parse and (listing_url or "").strip():
        try:
            return await generate_aqua_link_parse(
                user_api_key=user_api_key,
                team_api_key=team_api_key,
                service=service,
                listing_url=str(listing_url),
                buyer_name=buyer_name,
                address=address,
                balance_checker=balance_checker,
                timeout_sec=timeout_sec,
            )
        except AquaError as e:
            if _is_auth_error(e) or not (name or "").strip() or price is None:
                raise
    resolved_img = (image or "").strip()
    if not resolved_img.lower().startswith(("http://", "https://")):
        default = (getattr(config, "AQUA_DEFAULT_IMAGE_URL", None) or "").strip()
        if default.lower().startswith(("http://", "https://")):
            resolved_img = default
    return await generate_aqua_link_no_parse(
        user_api_key=user_api_key,
        team_api_key=team_api_key,
        service=service,
        name=str(name or ""),
        price=price if price is not None else "0",
        buyer_name=buyer_name,
        address=address,
        image=resolved_img or image,
        balance_checker=balance_checker,
        timeout_sec=timeout_sec,
    )
