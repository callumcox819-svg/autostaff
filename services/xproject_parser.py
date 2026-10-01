"""XProject parser API: https://api.xproject.digital/docs"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)

XPROJECT_API_BASE = "https://api.xproject.digital"


class XProjectError(Exception):
    def __init__(self, message: str, *, status: int = 0):
        super().__init__(message)
        self.status = int(status or 0)


def _detail(data: Any, fallback: str) -> str:
    if isinstance(data, dict):
        d = data.get("detail")
        if isinstance(d, str) and d.strip():
            return d.strip()
        if isinstance(d, list):
            return "; ".join(str(x) for x in d)[:400]
    return fallback


async def _request(
    method: str,
    path: str,
    *,
    api_key: str,
    json_body: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
    timeout_sec: float = 20.0,
) -> Any:
    key = (api_key or "").strip()
    if not key:
        raise XProjectError("Нет ключа XProject")
    url = f"{XPROJECT_API_BASE.rstrip('/')}{path}"
    headers = {
        "X-API-Key": key,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    timeout = aiohttp.ClientTimeout(
        total=timeout_sec, connect=8, sock_connect=8, sock_read=timeout_sec
    )
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.request(
                method, url, headers=headers, json=json_body, params=params
            ) as resp:
                text = await resp.text()
                try:
                    data = await resp.json(content_type=None)
                except Exception:
                    data = None
                if resp.status == 401:
                    raise XProjectError("Ключ парсера неверный.", status=401)
                if resp.status == 402:
                    raise XProjectError(
                        "Подписка на парсинг неактивна (402). Авто-парс остановлен.",
                        status=402,
                    )
                if resp.status == 409:
                    raise XProjectError(
                        _detail(data, "Такая задача уже запущена."),
                        status=409,
                    )
                if resp.status == 429:
                    raise XProjectError("Слишком много запросов к парсеру. Подожди.", status=429)
                if not (200 <= resp.status < 300):
                    raise XProjectError(
                        _detail(data, f"HTTP {resp.status}: {text[:240]}"),
                        status=resp.status,
                    )
                return data
    except XProjectError:
        raise
    except (aiohttp.ClientError, asyncio.TimeoutError, TimeoutError) as e:
        raise XProjectError(f"Сеть парсера: {e}") from e


async def fetch_schema(api_key: str) -> dict[str, Any]:
    data = await _request("GET", "/api/v1/parser/schema", api_key=api_key)
    return data if isinstance(data, dict) else {}


async def start_task(api_key: str, *, platform: str, filters: dict[str, Any]) -> dict[str, Any]:
    data = await _request(
        "POST",
        "/api/v1/parser/start",
        api_key=api_key,
        json_body={"platform": platform, "filters": filters or {}},
    )
    if not isinstance(data, dict):
        raise XProjectError("Парсер не вернул задачу")
    return data


async def list_tasks(api_key: str) -> list[dict[str, Any]]:
    data = await _request("GET", "/api/v1/parser/tasks", api_key=api_key)
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        for key in ("tasks", "items", "data"):
            rows = data.get(key)
            if isinstance(rows, list):
                return [x for x in rows if isinstance(x, dict)]
    return []


async def fetch_listings(
    api_key: str,
    task_id: int,
    *,
    cursor: int | None = None,
) -> dict[str, Any]:
    params: dict[str, Any] = {}
    if cursor is not None:
        params["cursor"] = int(cursor)
    data = await _request(
        "GET",
        f"/api/v1/parser/{int(task_id)}",
        api_key=api_key,
        params=params or None,
    )
    if not isinstance(data, dict):
        raise XProjectError("Плохой ответ выдачи парсера")
    return data


async def stop_task(api_key: str, task_id: int) -> None:
    try:
        await _request(
            "POST",
            f"/api/v1/parser/{int(task_id)}/stop",
            api_key=api_key,
            json_body={},
        )
    except XProjectError as e:
        if e.status in {404}:
            return
        raise
