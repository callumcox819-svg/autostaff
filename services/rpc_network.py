"""RPC / Continental Group Rental Public API.

https://docs.continental-group-rental.com/start
Auth: заголовок X-API-KEY
Base: свой API-домен проекта (не домен документации).
Create: POST /api/v1/ad/create
"""

from __future__ import annotations

import logging
import os
from typing import Any
from urllib.parse import urlparse

import aiohttp

from services.goo_network import GooError, price_to_api_number

logger = logging.getLogger(__name__)

RPC_API_BASE_DEFAULT = ""


class RpcError(Exception):
    pass


def rpc_env_api_base() -> str:
    return (
        os.getenv("RPC_API_BASE")
        or os.getenv("CONTINENTAL_API_BASE")
        or os.getenv("CGR_API_BASE")
        or RPC_API_BASE_DEFAULT
    ).strip().rstrip("/")


def normalize_rpc_api_base(raw: str | None, *, fallback: str | None = None) -> str:
    s = (raw or "").strip().strip('"').strip("'")
    if not s:
        s = (fallback if fallback is not None else rpc_env_api_base()) or ""
        s = s.strip()
    if not s:
        return ""
    if s.lower().startswith("http://"):
        s = "https://" + s[7:]
    if not s.lower().startswith("https://"):
        s = "https://" + s
    s = s.rstrip("/")
    for suffix in ("/api/v1", "/api"):
        if s.lower().endswith(suffix):
            s = s[: -len(suffix)].rstrip("/")
    host = urlparse(s).hostname or ""
    if not host or "." not in host:
        raise RpcError(f"Некорректный API-домен RPC: {raw!r}")
    return s


def _auth_headers(*, api_key: str) -> dict[str, str]:
    key = (api_key or "").strip()
    if not key:
        raise RpcError("Не задан API-ключ RPC (X-API-KEY)")
    return {
        "X-API-KEY": key,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def rpc_method_for_link_type(link_type: str | None) -> str:
    lt = (link_type or "lk").strip().lower()
    if lt in {"card", "1", "1_0"}:
        return "1_0"
    if lt in {"other", "rental", "r", "traffic", "t"}:
        return "rental"
    if lt in {"verify", "v"}:
        return "verify"
    return "2_0"


def _price_number(price: str | float | int | None) -> float:
    try:
        return price_to_api_number(price)
    except GooError as e:
        raise RpcError(str(e)) from e


def _image_mime(url: str) -> str:
    path = urlparse(url).path.lower()
    if path.endswith(".png"):
        return "image/png"
    if path.endswith(".webp"):
        return "image/webp"
    if path.endswith(".gif"):
        return "image/gif"
    return "image/jpeg"


def extract_rpc_link(data: dict[str, Any], *, method: str = "2_0") -> str:
    if not isinstance(data, dict):
        raise RpcError(f"Bad response: {data!r}")
    status = data.get("status")
    if status in {False, "error"}:
        raise RpcError(str(data.get("error") or data.get("message") or data)[:400])
    block = data.get("data") if isinstance(data.get("data"), dict) else data
    want = (method or "2_0").strip() or "2_0"
    shorts = block.get("short_links")
    if isinstance(shorts, list):
        chosen: list[str] = []
        for row in shorts:
            if not isinstance(row, dict):
                continue
            m = str(row.get("method") or "").strip()
            url = (
                str(row.get("private") or "").strip()
                or str(row.get("public") or "").strip()
            )
            if url.lower().startswith(("http://", "https://")):
                if m == want or (not m and want == "2_0"):
                    return url
                chosen.append(url)
        if chosen:
            return chosen[0]
    paths = block.get("paths") if isinstance(block.get("paths"), dict) else {}
    domains = block.get("domains") if isinstance(block.get("domains"), dict) else {}
    phishing = paths.get("phishing") if isinstance(paths.get("phishing"), dict) else {}
    payment = paths.get("payment") if isinstance(paths.get("payment"), dict) else {}
    path = (
        phishing.get(want)
        or phishing.get("2_0")
        or payment.get(want)
        or payment.get("2_0")
        or ""
    )
    path = str(path or "").strip()
    host = str(domains.get("general") or domains.get("custom") or domains.get("short") or "").strip()
    host = host.replace("https://", "").replace("http://", "").split("/")[0]
    if host and path:
        if not path.startswith("/"):
            path = "/" + path
        return f"https://{host}{path}"
    tag = str(block.get("tag") or "").strip()
    short_host = str(domains.get("short") or "").strip()
    short_host = short_host.replace("https://", "").replace("http://", "").split("/")[0]
    if short_host and tag:
        return f"https://{short_host}/r/{tag}"
    raise RpcError(f"No link in response: {str(data)[:300]}")


async def _post_json(
    base: str,
    path: str,
    body: dict[str, Any],
    *,
    api_key: str,
    timeout_sec: float = 45.0,
) -> dict[str, Any]:
    root = normalize_rpc_api_base(base)
    if not root:
        raise RpcError(
            "Не задан API-домен RPC. Команды API → RPC → API-домен "
            "(или переменная RPC_API_BASE на сервере)."
        )
    url = f"{root}{path}"
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
                if resp.status == 429:
                    raise RpcError("RPC лимит 50 req/min — подождите пару секунд и нажмите снова.")
                if not (200 <= resp.status < 300):
                    msg = ""
                    if isinstance(data, dict):
                        msg = str(data.get("error") or data.get("message") or "")
                    raise RpcError(f"HTTP {resp.status}: {msg or text[:300]}")
                if not isinstance(data, dict):
                    raise RpcError(f"Bad JSON: {text[:300]}")
                if data.get("status") == "error":
                    raise RpcError(str(data.get("error") or data)[:400])
                return data
    except aiohttp.ClientError as e:
        raise RpcError(f"Сеть ({url}): {e}") from e


async def rpc_create_ad(
    *,
    api_key: str,
    api_base: str,
    country_code: str,
    service_code: str,
    title: str,
    price: str | float | int,
    full_name: str,
    address: str,
    image: str | None = None,
    link_type: str = "lk",
) -> str:
    cc = (country_code or "").strip().upper()
    svc = (service_code or "").strip().lower()
    name = (title or "").strip()
    buyer = (full_name or "").strip()
    addr = (address or "").strip()
    if not cc:
        raise RpcError("Не задана страна RPC")
    if not svc:
        raise RpcError("Не задан код сервиса RPC (из /geo)")
    if not name:
        raise RpcError("Нет названия объявления")
    if not buyer:
        raise RpcError("Не задано ФИО (RPC → ФИО)")
    if not addr:
        raise RpcError("Не задан адрес (RPC → Адрес)")
    body: dict[str, Any] = {
        "country_code": cc,
        "service_code": svc,
        "title": name,
        "price": _price_number(price),
        "profile": {"full_name": buyer, "address": addr},
    }
    img = (image or "").strip()
    if img.lower().startswith(("http://", "https://")):
        body["images"] = {"0": {"url": img, "type": _image_mime(img)}}
    data = await _post_json(
        api_base,
        "/api/v1/ad/create",
        body,
        api_key=api_key,
    )
    method = rpc_method_for_link_type(link_type)
    link = extract_rpc_link(data, method=method)
    logger.info("rpc ad/create ok service=%s country=%s", svc, cc)
    return link
