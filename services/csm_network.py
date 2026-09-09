"""CSM / meow network Internal API — https://meowsavings.cloud/api-docs"""

from __future__ import annotations

import logging
import os
from typing import Any

import aiohttp

from services.csm_catalog import is_verify_service

logger = logging.getLogger(__name__)

CSM_API_BASE = (
    os.getenv("CSM_API_BASE")
    or os.getenv("MEOW_API_BASE")
    or "https://api.meowsavings.cloud"
).strip().rstrip("/")


class CsmError(Exception):
    pass


def _auth_headers(*, api_key: str) -> dict[str, str]:
    key = (api_key or "").strip()
    if not key:
        raise CsmError("Не задан API-ключ CSM")
    if not key.lower().startswith("mw_"):
        # всё равно пробуем, но Bearer как в доке
        pass
    return {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0",
        "Origin": "https://meowsavings.cloud",
        "Referer": "https://meowsavings.cloud/api-docs",
    }


def _extract_link(data: dict[str, Any]) -> str:
    if not isinstance(data, dict):
        raise CsmError(f"Bad response: {data!r}")
    if data.get("status") is False:
        raise CsmError(str(data.get("error") or data)[:400])
    result = data.get("result")
    if isinstance(result, dict):
        for key in ("link", "url", "href"):
            val = result.get(key)
            if isinstance(val, str) and val.strip().lower().startswith(("http://", "https://")):
                return val.strip()
    for key in ("link", "url", "message"):
        val = data.get(key)
        if isinstance(val, str) and val.strip().lower().startswith(("http://", "https://")):
            return val.strip()
    raise CsmError(f"No link in response: {str(data)[:300]}")


async def _post(path: str, body: dict[str, Any], *, api_key: str, timeout_sec: float = 45.0) -> dict[str, Any]:
    url = f"{CSM_API_BASE}{path}"
    headers = _auth_headers(api_key=api_key)
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
                        msg = str(data.get("error") or data.get("message") or "")
                    raise CsmError(f"HTTP {resp.status}: {msg or text[:300]}")
                if not isinstance(data, dict):
                    raise CsmError(f"Bad JSON: {text[:300]}")
                return data
    except aiohttp.ClientError as e:
        raise CsmError(f"Сеть ({url}): {e}") from e


async def csm_generate_parse(
    *,
    api_key: str,
    service_key: str,
    listing_url: str,
    profile_id: str = "",
    client_name: str = "",
    address: str = "",
    balance_input: bool = False,
) -> str:
    listing = (listing_url or "").strip()
    if not listing:
        raise CsmError("Нужен listingUrl")
    body: dict[str, Any] = {
        "serviceKey": (service_key or "").strip(),
        "listingUrl": listing,
        "balanceInput": bool(balance_input),
    }
    pid = (profile_id or "").strip()
    if pid:
        body["profileId"] = pid
    else:
        if (client_name or "").strip():
            body["clientName"] = client_name.strip()
        if (address or "").strip():
            body["address"] = address.strip()
    data = await _post("/api/internal/order-link/create-parse", body, api_key=api_key)
    return _extract_link(data)


async def csm_generate_manual(
    *,
    api_key: str,
    service_key: str,
    product_title: str = "",
    product_price: str = "",
    image_url: str = "",
    profile_id: str = "",
    client_name: str = "",
    address: str = "",
    seller_name: str = "",
    balance_input: bool = False,
) -> str:
    sk = (service_key or "").strip()
    body: dict[str, Any] = {"serviceKey": sk}
    if is_verify_service(sk):
        name = (seller_name or product_title or "").strip()
        if not name:
            raise CsmError("Для Verify нужен sellerName")
        body["sellerName"] = name
    else:
        title = (product_title or "").strip()
        if not title:
            raise CsmError("Нужен productTitle")
        body["productTitle"] = title
        body["productPrice"] = (product_price or "").strip() or "0"
        if (image_url or "").strip():
            body["imageUrl"] = image_url.strip()
        body["balanceInput"] = bool(balance_input)
        pid = (profile_id or "").strip()
        if pid:
            body["profileId"] = pid
        else:
            if not (client_name or "").strip() or not (address or "").strip():
                raise CsmError("Нужен profileId либо clientName + address")
            body["clientName"] = client_name.strip()
            body["address"] = address.strip()
    data = await _post("/api/internal/order-link/create", body, api_key=api_key)
    return _extract_link(data)
