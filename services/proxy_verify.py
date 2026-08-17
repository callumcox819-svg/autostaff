"""Проверка прокси (SOCKS5 / HTTP): туннель + SMTP (как при рассылке)."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Tuple
from urllib.parse import urlsplit

from models import Proxy
from proxy_manager import (
    HTTP_TYPES,
    MAILING_PROXY_TYPES,
    SOCKS5_TYPES,
    connect_via_mailing_proxy,
    normalize_proxy_type,
    proxy_type_name,
)
from services.residential_proxy import is_residential_gateway_host

logger = logging.getLogger(__name__)

MAILING_PROXY_DEAD_PREFIX = "[mailing]"

PROXY_CHECK_RETRIES = max(1, min(4, int(os.getenv("PROXY_CHECK_RETRIES", "2"))))
PROXY_CHECK_RETRY_PAUSE_SEC = max(
    0.5, min(5.0, float(os.getenv("PROXY_CHECK_RETRY_PAUSE_SEC", "2")))
)

PROXY_ADD_SMTP_CHECK = (os.getenv("PROXY_ADD_SMTP_CHECK", "1") or "").strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)
PROXY_TUNNEL_CHECK_TIMEOUT = max(
    5, min(25, int(os.getenv("PROXY_TUNNEL_CHECK_TIMEOUT", "12")))
)


def proxy_to_dict(proxy: Proxy | dict[str, Any]) -> dict[str, Any]:
    if isinstance(proxy, dict):
        d = dict(proxy)
        d["type"] = normalize_proxy_type(d.get("type"))
        return d
    if isinstance(proxy, Proxy):
        try:
            from handlers.proxies import heal_misparsed_proxy_row

            heal_misparsed_proxy_row(proxy)
        except Exception:
            pass
    return {
        "host": proxy.host,
        "port": int(proxy.port),
        "username": proxy.username,
        "password": proxy.password,
        "type": proxy_type_name(proxy),
    }


def build_proxy_url(proxy: Proxy | dict[str, Any]) -> str:
    d = proxy_to_dict(proxy)
    proxy_type = normalize_proxy_type(d.get("type"))
    host = d["host"]
    port = int(d["port"])
    user = (d.get("username") or "").strip()
    pwd = (d.get("password") or "").strip()
    if user and pwd:
        return f"{proxy_type}://{user}:{pwd}@{host}:{port}"
    return f"{proxy_type}://{host}:{port}"


def is_socks5_type(proxy_type: str) -> bool:
    return normalize_proxy_type(proxy_type) in SOCKS5_TYPES


def _test_proxy_tunnel_sync(d: dict[str, Any], *, timeout: int = 12) -> Tuple[bool, str]:
    """Быстрая проверка туннеля до smtp.gmail.com:587 (как при send)."""
    ptype = normalize_proxy_type(d.get("type"))
    if ptype not in MAILING_PROXY_TYPES:
        return False, "Нужен socks5, socks4 или http прокси."

    thost, tport = "smtp.gmail.com", 587
    row = _proxy_row_from_dict(d)
    s = None
    try:
        s = connect_via_mailing_proxy(row, thost, tport, timeout=float(timeout))
        label = ptype.upper() if ptype in HTTP_TYPES else ptype
        return True, f"{label} OK -> {thost}:{tport}"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"
    finally:
        if s is not None:
            try:
                s.close()
            except Exception:
                pass


async def _test_proxy_tunnel_handshake(
    proxy: Proxy | dict[str, Any], *, timeout: int = 12
) -> Tuple[bool, str]:
    d = proxy_to_dict(proxy)
    return await asyncio.to_thread(_test_proxy_tunnel_sync, d, timeout=timeout)


def _tunnel_types_to_try(d: dict[str, Any]) -> list[str]:
    primary = normalize_proxy_type(d.get("type")) or "socks5"
    types: list[str] = []
    for t in (primary, "socks5", "socks5h"):
        if t not in types:
            types.append(t)
    if is_residential_gateway_host(str(d.get("host") or "")):
        if "http" not in types:
            types.append("http")
    return types


async def _test_proxy_tunnel_handshake_fallback(
    proxy: Proxy | dict[str, Any], *, timeout: int = 12
) -> Tuple[bool, str, str]:
    """SOCKS5 → socks5h; Loma ещё HTTP CONNECT, если SOCKS-гейт лежит."""
    d = proxy_to_dict(proxy)
    last = "Нужен socks5, socks4 или http прокси."
    for t in _tunnel_types_to_try(d):
        alt = dict(d)
        alt["type"] = t
        tmo = timeout
        if is_residential_gateway_host(str(d.get("host") or "")):
            tmo = max(timeout, 20)
        ok, info = await _test_proxy_tunnel_handshake(alt, timeout=tmo)
        if ok:
            return True, info, t
        last = info
    return False, last, normalize_proxy_type(d.get("type"))


def _proxy_row_from_dict(d: dict[str, Any]) -> Proxy:
    return Proxy(
        host=str(d["host"]),
        port=int(d["port"]),
        username=d.get("username"),
        password=d.get("password"),
        type=normalize_proxy_type(d.get("type")),
    )


async def test_smtp_tunnel(proxy: Proxy | dict[str, Any], *, timeout: int = 20) -> Tuple[bool, str]:
    from proxy_manager import test_smtp_tunnel_async

    row = _proxy_row_from_dict(proxy_to_dict(proxy))
    return await test_smtp_tunnel_async(row, timeout=timeout)


def classify_proxy_check_result(ok: bool, info: str) -> bool | None:
    if ok:
        return True
    return None


def is_mailing_marked_dead(last_error: str | None) -> bool:
    return (last_error or "").strip().startswith(MAILING_PROXY_DEAD_PREFIX)


def is_tunnel_only_smtp_check_failure(info: str) -> bool:
    """Туннель до :587 есть, полный SMTP-handshake не успел (часто residential / Loma)."""
    t = info or ""
    if "Туннель OK" in t:
        return True
    return "туннель ok" in t.lower() and "smtp-check не успел" in t.lower()


def check_error_worth_retry(info: str) -> bool:
    t = (info or "").lower()
    return any(
        x in t
        for x in (
            "timeout",
            "timed out",
            "заняла слишком",
            "туннель до smtp",
            "ehlo",
            "connection reset",
            "unexpectedly closed",
            "temporarily",
        )
    )


def apply_proxy_check_to_row(row: Proxy, ok: bool, info: str) -> None:
    classified = classify_proxy_check_result(ok, info)
    if classified is True:
        row.is_active = True
        row.last_error = None
        return
    if row.is_active is not False:
        row.is_active = None
    row.last_error = (info or "")[:500] if not ok else None


def heal_proxy_rows_from_stale_check_markers(proxies: list[Proxy]) -> None:
    for row in proxies:
        if row.is_active is False and not is_mailing_marked_dead(row.last_error):
            row.is_active = None


async def test_proxy_tunnel_only(
    proxy: Proxy | dict[str, Any], *, timeout: int | None = None
) -> Tuple[bool, str]:
    """
    Быстро: только CONNECT до smtp.gmail.com:587 (~1–5 с на Loma).
    (False, «Туннель OK…») = 🟡, годится для рассылки.
    """
    d = proxy_to_dict(proxy)
    ptype = normalize_proxy_type(d.get("type"))
    if ptype not in MAILING_PROXY_TYPES:
        return False, "Нужен socks5, socks4 или http прокси."
    tmo = PROXY_TUNNEL_CHECK_TIMEOUT if timeout is None else max(5, min(25, int(timeout)))
    tunnel_ok, tunnel_info, resolved_type = await _test_proxy_tunnel_handshake_fallback(
        proxy, timeout=tmo
    )
    if isinstance(proxy, dict) and resolved_type:
        proxy["type"] = resolved_type
    d["type"] = resolved_type
    if not tunnel_ok:
        return False, tunnel_info
    return False, f"Туннель OK ({tunnel_info})"


async def test_proxy_for_add(
    proxy: Proxy | dict[str, Any], *, smtp_timeout: int = 42, smtp: bool | None = None
) -> Tuple[bool, str]:
    """
    Добавление прокси: по умолчанию только туннель (PROXY_ADD_SMTP_CHECK=1 — полный SMTP).
    """
    do_smtp = PROXY_ADD_SMTP_CHECK if smtp is None else bool(smtp)
    d = proxy_to_dict(proxy)
    ptype = normalize_proxy_type(d.get("type"))
    if ptype not in MAILING_PROXY_TYPES:
        return False, "Нужен socks5, socks4 или http прокси."

    tmo = PROXY_TUNNEL_CHECK_TIMEOUT
    if is_residential_gateway_host(str(d.get("host") or "")):
        tmo = max(tmo, 20)
    tunnel_ok, tunnel_info, resolved_type = await _test_proxy_tunnel_handshake_fallback(
        proxy, timeout=tmo
    )
    if isinstance(proxy, dict):
        proxy["type"] = resolved_type
    d["type"] = resolved_type
    ptype = resolved_type
    if not tunnel_ok:
        return False, tunnel_info

    if not do_smtp:
        return False, f"Туннель OK ({tunnel_info}) · residential: без Gmail SMTP-check"

    smtp_ok, smtp_info = await test_smtp_tunnel(proxy, timeout=max(20, int(smtp_timeout)))
    if not smtp_ok and ptype == "socks5" and check_error_worth_retry(smtp_info or ""):
        alt = dict(d)
        alt["type"] = "socks5h"
        smtp_ok, smtp_info = await test_smtp_tunnel(alt, timeout=max(20, int(smtp_timeout)))
    if smtp_ok:
        return True, smtp_info
    if "занят" in (smtp_info or "").lower():
        return False, f"Туннель OK ({tunnel_info}). SMTP занят: {smtp_info}"
    return False, f"Туннель OK, но SMTP+STARTTLS не прошёл: {smtp_info}"


async def recover_tunnel_only_after_check_timeout(
    proxy: Proxy | dict[str, Any],
) -> Tuple[bool, str]:
    """Если общий wait_for оборвал проверку — быстрый туннель, чтобы не отклонять рабочий Loma."""
    tunnel_ok, tunnel_info, resolved = await _test_proxy_tunnel_handshake_fallback(
        proxy, timeout=18
    )
    if isinstance(proxy, dict):
        proxy["type"] = resolved
    if not tunnel_ok:
        return False, "Timeout: проверка прокси заняла слишком долго"
    return (
        False,
        f"Туннель OK ({tunnel_info}). SMTP-check не успел — прокси 🟡, в рассылке попробует",
    )


async def _test_proxy_once(proxy: Proxy | dict[str, Any], *, timeout: int = 20) -> Tuple[bool, str]:
    """Сначала быстрый туннель (без lock), затем SMTP+STARTTLS как при /send."""
    d = proxy_to_dict(proxy)
    ptype = normalize_proxy_type(d.get("type"))
    if ptype not in MAILING_PROXY_TYPES:
        return False, "Нужен socks5, socks4 или http прокси."

    tunnel_timeout = max(8, min(int(timeout), 16))
    tunnel_ok, tunnel_info, resolved_type = await _test_proxy_tunnel_handshake_fallback(
        proxy, timeout=tunnel_timeout
    )
    if isinstance(proxy, dict):
        proxy["type"] = resolved_type
    d["type"] = resolved_type
    ptype = resolved_type
    if not tunnel_ok:
        return False, tunnel_info

    smtp_timeout = max(25, min(int(timeout), 50))
    smtp_ok, smtp_info = await test_smtp_tunnel(proxy, timeout=smtp_timeout)
    if not smtp_ok and ptype == "socks5" and check_error_worth_retry(smtp_info or ""):
        alt = dict(d)
        alt["type"] = "socks5h"
        smtp_ok, smtp_info = await test_smtp_tunnel(alt, timeout=smtp_timeout)
    if smtp_ok:
        return True, smtp_info
    if "занят" in (smtp_info or "").lower():
        return False, f"Туннель OK ({tunnel_info}). SMTP занят: {smtp_info}"
    return False, f"Туннель OK, но SMTP+STARTTLS не прошёл: {smtp_info}"


async def test_proxy(
    proxy: Proxy | dict[str, Any], *, timeout: int = 20, retries: int | None = None
) -> Tuple[bool, str]:
    attempts = max(1, int(retries if retries is not None else PROXY_CHECK_RETRIES))
    last_info = ""
    for attempt in range(1, attempts + 1):
        ok, info = await _test_proxy_once(proxy, timeout=timeout)
        if ok:
            return True, info
        last_info = info or ""
        if attempt < attempts and check_error_worth_retry(last_info):
            logger.info(
                "proxy check retry %s/%s: %s",
                attempt,
                attempts,
                last_info[:120],
            )
            await asyncio.sleep(PROXY_CHECK_RETRY_PAUSE_SEC)
            continue
        break
    return False, last_info


async def test_proxy_url(proxy_url: str, *, timeout: int = 20) -> Tuple[bool, str]:
    p = (proxy_url or "").strip()
    scheme = normalize_proxy_type(urlsplit(p).scheme or "socks5")
    if scheme not in MAILING_PROXY_TYPES:
        return False, "Нужен socks5://, socks4:// или http://"
    return await test_proxy(
        {
            "host": urlsplit(p).hostname or "",
            "port": urlsplit(p).port or (8080 if scheme in HTTP_TYPES else 1080),
            "username": urlsplit(p).username,
            "password": urlsplit(p).password,
            "type": scheme,
        },
        timeout=timeout,
    )


async def refresh_proxies_status(
    session,
    user_id: int,
    *,
    concurrency: int = 10,
    timeout: int = 20,
) -> tuple[int, int, int]:
    from sqlalchemy import select as sa_select

    proxies = list(
        (
            await session.execute(sa_select(Proxy).where(Proxy.user_id == int(user_id)))
        ).scalars()
    )
    if not proxies:
        return 0, 0, 0

    try:
        from handlers.proxies import heal_misparsed_proxy_row

        if any(heal_misparsed_proxy_row(p) for p in proxies):
            await session.commit()
            for p in proxies:
                try:
                    await session.refresh(p)
                except Exception:
                    pass
    except Exception:
        logger.exception("heal_misparsed_proxy_row failed")

    snapshots: list[tuple[int, dict[str, Any]]] = []
    for p in proxies:
        try:
            snapshots.append((int(p.id), proxy_to_dict(p)))
        except Exception:
            logger.exception("proxy snapshot failed id=%s", getattr(p, "id", None))
            continue

    sem = asyncio.Semaphore(max(1, concurrency))
    results: list[tuple[int, bool, str]] = []

    per_proxy_timeout = max(12, int(timeout))

    async def _one(pid: int, d: dict[str, Any]) -> None:
        async with sem:
            try:
                ok, info = await asyncio.wait_for(
                    test_proxy(d, timeout=per_proxy_timeout),
                    timeout=per_proxy_timeout * 2 + 10,
                )
            except asyncio.TimeoutError:
                ok, info = False, "Timeout: проверка прокси заняла слишком долго"
            except Exception as e:
                ok, info = False, f"{type(e).__name__}: {e}"
        results.append((pid, ok, info))

    await asyncio.gather(*[_one(pid, d) for pid, d in snapshots])

    ok_n = 0
    fail_n = 0
    for pid, ok, info in results:
        row = await session.get(Proxy, int(pid))
        if not row:
            continue
        apply_proxy_check_to_row(row, ok, info or "")
        if ok:
            ok_n += 1
        else:
            fail_n += 1

    all_rows = list(
        (await session.execute(sa_select(Proxy).where(Proxy.user_id == int(user_id)))).scalars()
    )
    heal_proxy_rows_from_stale_check_markers(all_rows)

    await session.commit()
    return ok_n, fail_n, len(proxies)
