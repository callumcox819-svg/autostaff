"""GAG API — POST /generate (triangleblackword и аналоги)."""

from __future__ import annotations

import logging
import os
import re
from typing import Any

import aiohttp

from config import config
from region import format_item_price
from services.aqua_keys import normalize_aqua_api_key
from utils.ui_emoji import menu_path

logger = logging.getLogger(__name__)

_SETTINGS_KEY = menu_path(("settings", ""), ("key", ""))


class AquaError(Exception):
    pass


def _truthy(name: str, default: str = "0") -> bool:
    return (os.getenv(name, default) or "").strip().lower() in {"1", "true", "yes", "on"}


def generate_api_base() -> str:
    """Базовый URL домена генерации (без /generate)."""
    raw = (getattr(config, "GAG_API_BASE", None) or os.getenv("GAG_API_BASE") or "").strip().rstrip("/")
    if raw.endswith("/generate"):
        raw = raw[: -len("/generate")].rstrip("/")
    return raw


def generate_api_configured() -> bool:
    return bool(generate_api_base())


def _generate_domain_num() -> int:
    try:
        n = int(getattr(config, "GAG_GENERATE_DOMAIN", None) or os.getenv("GAG_GENERATE_DOMAIN", "1"))
    except (TypeError, ValueError):
        n = 1
    return max(1, min(8, n))


def _link_version() -> str:
    v = (getattr(config, "GAG_LINK_VERSION", None) or os.getenv("GAG_LINK_VERSION", "lk") or "lk").strip()
    return v or "lk"


def _balance_checker_flag(explicit: bool | None = None) -> int:
    if explicit is not None:
        return 1 if explicit else 0
    if _truthy("GAG_BALANCE_CHECKER"):
        return 1
    return 0


def price_to_api_string(price: str | float | int | None) -> str:
    if price is None:
        raise AquaError("Нет цены")
    if isinstance(price, (int, float)):
        return format_item_price(str(price))
    raw = str(price).strip()
    if not raw:
        raise AquaError("Нет цены")
    return format_item_price(raw)


def _extract_link(data: dict[str, Any]) -> str:
    for key in ("url", "link", "message"):
        val = (data.get(key) or "").strip()
        if val.lower().startswith(("http://", "https://")):
            return val
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
    raise AquaError(f"No link in response: {str(data)[:300]}")


async def _post_generate(body: dict[str, Any], *, timeout_sec: float = 30.0) -> dict[str, Any]:
    base = generate_api_base()
    if not base:
        raise AquaError(
            "Домен генерации не задан. На сервере: GAG_API_BASE=https://triangleblackword.cfd"
        )

    apikey = normalize_aqua_api_key(str(body.get("apikey") or ""))
    if not apikey:
        raise AquaError(f"Не задан личный API key ({_SETTINGS_KEY})")

    payload = dict(body)
    payload["apikey"] = apikey

    url = f"{base}/generate"
    headers = {"Content-Type": "application/json"}
    timeout = aiohttp.ClientTimeout(total=timeout_sec)

    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, json=payload, headers=headers) as resp:
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
                        raise AquaError(
                            f"HTTP {resp.status}: неверный apikey или доступ запрещён.\n\n"
                            f"Проверь личный ключ в {_SETTINGS_KEY} (из панели GAG)."
                        ) from err
                    raise err
                if not isinstance(data, dict):
                    raise AquaError(f"Bad JSON: {text[:300]}")
                if data.get("success") is False:
                    raise AquaError(str(data.get("message") or data)[:300])
                return data
    except aiohttp.ClientError as e:
        raise AquaError(f"Сеть ({url}): {e}") from e


async def verify_gag_auth(
    *,
    user_api_key: str,
    team_api_key: str = "",
    timeout_sec: float = 15.0,
) -> bool:
    """Проверка: apikey пользователя + GAG_API_BASE на сервере."""
    _ = team_api_key  # legacy, не используется
    key = normalize_aqua_api_key(user_api_key)
    if not key:
        raise AquaError(f"Личный API key не задан ({_SETTINGS_KEY})")
    if not generate_api_base():
        raise AquaError(
            "GAG_API_BASE не задан на сервере.\n"
            "Пример: https://triangleblackword.cfd"
        )
    if not re.fullmatch(r"[a-f0-9]{16,64}", key, flags=re.I):
        logger.warning("GAG apikey не похож на hex-токен (длина/формат)")
    return True


async def generate_aqua_link_no_parse(
    *,
    user_api_key: str,
    team_api_key: str = "",
    service: str,
    name: str,
    price: str | float | int,
    buyer_name: str,
    address: str,
    image: str | None = None,
    balance_checker: bool = False,
    timeout_sec: float = 30.0,
    domain: int | None = None,
) -> str:
    """POST {GAG_API_BASE}/generate — ссылка по названию/цене/фото."""
    _ = team_api_key
    title = (name or "").strip()
    if not title:
        raise AquaError("Нет названия товара")
    buyer = (buyer_name or "").strip()
    addr = (address or "").strip()
    if not buyer:
        raise AquaError("Не задано имя получателя (профиль)")
    if not addr:
        raise AquaError("Не задан адрес доставки (профиль)")

    img = (image or "").strip()
    if not img.lower().startswith(("http://", "https://")):
        default = (getattr(config, "AQUA_DEFAULT_IMAGE_URL", None) or "").strip()
        if default.lower().startswith(("http://", "https://")):
            img = default

    body: dict[str, Any] = {
        "apikey": normalize_aqua_api_key(user_api_key),
        "title": title,
        "price": price_to_api_string(price),
        "name": buyer,
        "address": addr,
        "service": service,
        "balanceChecker": _balance_checker_flag(balance_checker),
        "domain": max(1, min(8, int(domain))) if domain is not None else _generate_domain_num(),
        "version": _link_version(),
    }
    if img.lower().startswith(("http://", "https://")):
        body["image"] = img

    data = await _post_generate(body, timeout_sec=timeout_sec)
    return _extract_link(data)


async def generate_aqua_link_parse(
    *,
    user_api_key: str,
    team_api_key: str = "",
    service: str,
    listing_url: str,
    buyer_name: str,
    address: str,
    balance_checker: bool = False,
    timeout_sec: float = 30.0,
    name: str | None = None,
    price: str | float | int | None = None,
    image: str | None = None,
) -> str:
    """API /generate не парсит URL — используем title/price из оффера."""
    _ = (listing_url, team_api_key)
    if not (name or "").strip() or price is None:
        raise AquaError("Для генерации нужны название и цена (URL парсинг не поддерживается API)")
    return await generate_aqua_link_no_parse(
        user_api_key=user_api_key,
        service=service,
        name=str(name),
        price=price,
        buyer_name=buyer_name,
        address=address,
        image=image,
        balance_checker=balance_checker,
        timeout_sec=timeout_sec,
    )


async def generate_aqua_link(
    *,
    user_api_key: str,
    team_api_key: str = "",
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
    domain: int | None = None,
) -> str:
    _ = (listing_url, prefer_parse, team_api_key)
    resolved_img = (image or "").strip()
    if not resolved_img.lower().startswith(("http://", "https://")):
        default = (getattr(config, "AQUA_DEFAULT_IMAGE_URL", None) or "").strip()
        if default.lower().startswith(("http://", "https://")):
            resolved_img = default
    return await generate_aqua_link_no_parse(
        user_api_key=user_api_key,
        service=service,
        name=str(name or ""),
        price=price if price is not None else "0",
        buyer_name=buyer_name,
        address=address,
        image=resolved_img or image,
        balance_checker=balance_checker,
        timeout_sec=timeout_sec,
        domain=domain,
    )
