from __future__ import annotations

import asyncio
import contextvars
import logging
import os
import random
from contextlib import asynccontextmanager
from typing import Optional

from sqlalchemy import select, or_

from models import Proxy

logger = logging.getLogger(__name__)


class _ReentrantAsyncLock:
    """Один event loop: рассылка держит lock в Session и снова в ProxySMTPContext."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._owner: asyncio.Task | None = None
        self._depth = 0

    async def acquire(self) -> None:
        task = asyncio.current_task()
        if task is not None and self._owner is task:
            self._depth += 1
            return
        await self._lock.acquire()
        self._owner = task
        self._depth = 1

    def release(self) -> None:
        if self._depth > 1:
            self._depth -= 1
            return
        self._owner = None
        self._depth = 0
        self._lock.release()

    async def __aenter__(self) -> "_ReentrantAsyncLock":
        await self.acquire()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        self.release()


_PROXY_LOCK = _ReentrantAsyncLock()
_DB_SOCKET_LOCK = _ReentrantAsyncLock()
import socket as _stdlib_socket
import smtplib as _smtplib

_SMTP_SOCKET_ORIG = _smtplib.socket
_SOCKET_GETADDRINFO_ORIG = None
_SMTP_TEST_HOST = (os.getenv("SMTP_TEST_HOST") or "smtp.gmail.com").strip()
_SMTP_TEST_PORT = int(os.getenv("SMTP_TEST_PORT") or "587")

_HTTP_SMTP_PROXY_CTX: contextvars.ContextVar[Proxy | None] = contextvars.ContextVar(
    "http_smtp_proxy",
    default=None,
)
_SMTP_GETSOCKET_PATCHED = False
# Глобальный PySocks/HTTP-патч активен (ProxySMTPContext). Isolated SMTP его не ставит.
_SMTP_GLOBAL_PROXY_ACTIVE = False

SOCKS5_TYPES = frozenset({"socks5", "socks5h"})
SOCKS4_TYPES = frozenset({"socks4", "socks4a"})
HTTP_TYPES = frozenset({"http", "https"})
MAILING_PROXY_TYPES = SOCKS5_TYPES | SOCKS4_TYPES | HTTP_TYPES


def normalize_proxy_type(t: str | None) -> str:
    t = (t or "socks5").strip().lower()
    if t in ("socks", "sock5", "socksv5"):
        return "socks5"
    if t in ("socks5h",):
        return "socks5h"
    if t in ("socks5",):
        return "socks5"
    if t in ("socks4a",):
        return "socks4a"
    if t in ("socks4",):
        return "socks4"
    if t in ("http", "https"):
        return "http"
    if t.startswith("socks5"):
        return "socks5"
    if t.startswith("socks4"):
        return "socks4a" if t.endswith("a") else "socks4"
    if t.startswith("socks"):
        return "socks5"
    return "socks5"


def proxy_type_name(proxy: Proxy) -> str:
    return normalize_proxy_type(getattr(proxy, "proxy_type", None) or proxy.type)


def is_socks5_proxy(proxy: Proxy) -> bool:
    t = proxy_type_name(proxy)
    return t in SOCKS5_TYPES or t.startswith("socks5")


def is_http_proxy(proxy: Proxy) -> bool:
    return proxy_type_name(proxy) in HTTP_TYPES


def is_socks4_proxy(proxy: Proxy) -> bool:
    return proxy_type_name(proxy) in SOCKS4_TYPES


def is_mailing_proxy(proxy: Proxy) -> bool:
    """SOCKS4/5 или HTTP — SMTP через CONNECT (PySocks)."""
    return (
        is_socks5_proxy(proxy)
        or is_socks4_proxy(proxy)
        or is_http_proxy(proxy)
    )


def socks_proxy_type_for(proxy: Proxy) -> int:
    import socks

    t = proxy_type_name(proxy)
    if is_http_proxy(proxy):
        return socks.HTTP
    if t == "socks4a":
        return socks.SOCKS4A
    if t == "socks4":
        return socks.SOCKS4
    return socks.SOCKS5


def socks_proxy_rdns(proxy: Proxy) -> bool:
    """Remote DNS: socks5h / socks4a; HTTP — локально; socks5 — по умолчанию remote (как раньше)."""
    t = proxy_type_name(proxy)
    if is_http_proxy(proxy):
        return False
    if t in ("socks5h", "socks4a"):
        return True
    if t == "socks4":
        return False
    return True


def _mailing_proxy_credentials(proxy: Proxy) -> tuple[str, int, str | None, str | None]:
    host = (proxy.host or "").strip()
    port = int(proxy.port or 0)
    if not host or not port:
        raise ValueError("Proxy host/port is empty")
    username = (proxy.username or "").strip() or None
    password = (proxy.password or "").strip() or None
    return host, port, username, password


def _http_proxy_tunnel_socket(
    proxy: Proxy,
    dest_host: str,
    dest_port: int,
    *,
    timeout: float,
) -> _stdlib_socket.socket:
    """
    HTTP CONNECT с Proxy-Authorization (PySocks для HTTP часто даёт 407 у residential-провайдеров).
    """
    import base64
    import http.client

    px_host, px_port, username, password = _mailing_proxy_credentials(proxy)
    conn = http.client.HTTPConnection(px_host, px_port, timeout=float(timeout))
    headers: dict[str, str] = {}
    if username and password:
        token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
        headers["Proxy-Authorization"] = f"Basic {token}"
    conn.set_tunnel(str(dest_host).strip(), int(dest_port), headers=headers)
    conn.connect()
    sock = conn.sock
    if sock is None:
        raise OSError("HTTP CONNECT: прокси не вернул сокет")
    sock.settimeout(float(timeout))
    return sock


def _ensure_smtp_http_connect_patch() -> None:
    global _SMTP_GETSOCKET_PATCHED
    if _SMTP_GETSOCKET_PATCHED:
        return

    _orig_get_socket = _smtplib.SMTP._get_socket

    def _get_socket(self, host, port, timeout):  # type: ignore[no-untyped-def]
        p = _HTTP_SMTP_PROXY_CTX.get()
        if p is not None and is_http_proxy(p):
            t = float(timeout if timeout is not None else 20)
            return _http_proxy_tunnel_socket(p, host, port, timeout=t)
        return _orig_get_socket(self, host, port, timeout)

    _smtplib.SMTP._get_socket = _get_socket  # type: ignore[method-assign]
    _SMTP_GETSOCKET_PATCHED = True


def mailing_socket_as_stdlib(sock, timeout: float):
    """
    SSL/STARTTLS на PySocks socksocket часто рвёт сессию
    (SMTPServerDisconnected). После SOCKS handshake берём обычный TCP fd.
    """
    import socket as stdlib

    if type(sock) is stdlib.socket:
        try:
            sock.settimeout(float(timeout))
        except Exception:
            pass
        return sock
    try:
        family = getattr(sock, "family", stdlib.AF_INET)
        sock_type = getattr(sock, "type", stdlib.SOCK_STREAM)
        proto = getattr(sock, "proto", 0)
        fd = sock.detach()
        out = stdlib.socket(family, sock_type, proto, fileno=fd)
        out.settimeout(float(timeout))
        return out
    except Exception:
        try:
            sock.settimeout(float(timeout))
        except Exception:
            pass
        return sock


def connect_via_mailing_proxy(
    proxy: Proxy,
    dest_host: str,
    dest_port: int,
    *,
    timeout: float,
) -> _stdlib_socket.socket:
    """
    TCP до dest через SOCKS4/5 или HTTP CONNECT — как при рассылке (изолированный сокет).
    """
    if not is_mailing_proxy(proxy):
        raise ValueError(
            f"Неподдерживаемый тип прокси: {proxy_type_name(proxy)!r} "
            f"(нужен socks5, socks4, http)"
        )

    if is_http_proxy(proxy):
        sock = _http_proxy_tunnel_socket(
            proxy,
            str(dest_host).strip(),
            int(dest_port),
            timeout=float(timeout),
        )
        return mailing_socket_as_stdlib(sock, timeout)

    import socks

    px_host, px_port, username, password = _mailing_proxy_credentials(proxy)
    kind = socks_proxy_type_for(proxy)
    rdns = socks_proxy_rdns(proxy)

    sock = socks.socksocket(_stdlib_socket.AF_INET, _stdlib_socket.SOCK_STREAM)
    sock.set_proxy(
        kind,
        px_host,
        px_port,
        username=username,
        password=password,
        rdns=rdns,
    )
    sock.settimeout(float(timeout))
    sock.connect((str(dest_host).strip(), int(dest_port)))
    return mailing_socket_as_stdlib(sock, timeout)


async def choose_proxy_for_user(
    session,
    user_id: int,
    *,
    exclude_ids: set[int] | None = None,
) -> Optional[Proxy]:
    """
    Возвращает один активный прокси пользователя (SOCKS5 или HTTP).
    """
    try:
        active_cond = or_(Proxy.is_active.is_(True), Proxy.is_active.is_(None))

        def _smtp_eligible(p: Proxy) -> bool:
            return is_mailing_proxy(p)

        all_rows = list(
            (
                await session.execute(
                    select(Proxy)
                    .where(Proxy.user_id == int(user_id))
                    .order_by(Proxy.id.asc())
                )
            ).scalars().all()
        )
        skip = exclude_ids or set()
        eligible = [p for p in all_rows if _smtp_eligible(p) and int(p.id) not in skip]
        preferred = [p for p in eligible if p.is_active is not False]
        items = preferred if preferred else eligible
        if not items:
            logger.warning(
                "no SMTP proxy for user_id=%s total=%s eligible=%s",
                user_id,
                len(all_rows),
                sum(1 for p in all_rows if _smtp_eligible(p)),
            )
            return None
        if len(items) == 1:
            return items[0]

        uid = int(user_id)
        chosen = random.choice(items)

        logger.info(
            "SMTP proxy selected user_id=%s proxy_id=%s %s:%s pool=%s",
            uid,
            chosen.id,
            chosen.host,
            chosen.port,
            len(items),
        )
        return chosen
    except Exception:
        logger.exception("choose_proxy_for_user failed")
        return None


def apply_proxy_to_smtplib(proxy: Proxy) -> None:
    """SOCKS → PySocks; HTTP → CONNECT через stdlib (Proxy-Authorization)."""
    global _SOCKET_GETADDRINFO_ORIG, _SMTP_GLOBAL_PROXY_ACTIVE

    if not is_mailing_proxy(proxy):
        raise ValueError(
            f"Неподдерживаемый тип прокси: {proxy_type_name(proxy)!r} "
            f"(нужен socks5, socks4 или http)"
        )

    host = (proxy.host or "").strip()
    port = int(proxy.port or 0)
    if not host or not port:
        raise ValueError("Proxy host/port is empty")

    if is_http_proxy(proxy):
        _ensure_smtp_http_connect_patch()
        try:
            reset_smtplib_proxy()
        except Exception:
            pass
        _HTTP_SMTP_PROXY_CTX.set(proxy)
        _SMTP_GLOBAL_PROXY_ACTIVE = True
        logger.info("SMTP HTTP proxy applied: %s:%s", host, port)
        return

    _HTTP_SMTP_PROXY_CTX.set(None)

    import socks
    import smtplib

    username = (proxy.username or "").strip() or None
    password = (proxy.password or "").strip() or None
    kind = socks_proxy_type_for(proxy)
    rdns = socks_proxy_rdns(proxy)

    socks.set_default_proxy(
        kind,
        host,
        port,
        username=username,
        password=password,
        rdns=rdns,
    )

    if _SOCKET_GETADDRINFO_ORIG is None:
        _SOCKET_GETADDRINFO_ORIG = _stdlib_socket.getaddrinfo

    def _getaddrinfo_ipv4(host, port, family=0, type=0, proto=0, flags=0):
        return _SOCKET_GETADDRINFO_ORIG(
            host,
            port,
            _stdlib_socket.AF_INET,
            type or _stdlib_socket.SOCK_STREAM,
            proto,
            flags,
        )

    _stdlib_socket.getaddrinfo = _getaddrinfo_ipv4  # type: ignore[assignment]

    socks.wrapmodule(smtplib)
    if hasattr(smtplib.socket, "getaddrinfo"):
        smtplib.socket.getaddrinfo = _getaddrinfo_ipv4  # type: ignore[attr-defined]

    _SMTP_GLOBAL_PROXY_ACTIVE = True
    logger.info(
        "SMTP proxy applied: %s %s:%s rdns=%s",
        proxy_type_name(proxy),
        host,
        port,
        rdns,
    )


async def test_smtp_tunnel_async(
    proxy: Proxy,
    *,
    timeout: int = 20,
    lock_timeout: float | None = None,
) -> tuple[bool, str]:
    """SMTP-проверка под lock — без гонок при параллельных тестах."""
    lt = lock_timeout
    if lt is None:
        try:
            lt = float(os.getenv("PROXY_SMTP_LOCK_TIMEOUT_SEC", "18"))
        except (TypeError, ValueError):
            lt = 18.0
    lt = max(3.0, min(60.0, float(lt)))
    try:
        await asyncio.wait_for(_PROXY_LOCK.acquire(), timeout=lt)
    except asyncio.TimeoutError:
        return False, "Бот занят (рассылка/IMAP). Повторите проверку через минуту."
    try:
        return await asyncio.to_thread(test_smtp_tunnel_sync, proxy, timeout=timeout)
    finally:
        try:
            _PROXY_LOCK.release()
        except Exception:
            pass


def test_smtp_tunnel_sync(proxy: Proxy, *, timeout: int = 20) -> tuple[bool, str]:
    """Проверка как при рассылке: прокси → SMTP :587."""
    if not is_mailing_proxy(proxy):
        return False, f"Неподдерживаемый тип: {(proxy.type or '?')!r}"

    apply_proxy_to_smtplib(proxy)
    try:
        s = _smtplib.SMTP(_SMTP_TEST_HOST, _SMTP_TEST_PORT, timeout=timeout)
        try:
            s.ehlo()
            s.starttls()
            s.ehlo()
        finally:
            try:
                s.close()
            except Exception:
                pass
        return True, f"SMTP+STARTTLS OK ({_SMTP_TEST_HOST}:{_SMTP_TEST_PORT})"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"
    finally:
        reset_smtplib_proxy()


def smtp_global_proxy_is_active() -> bool:
    """True только пока активен глобальный ProxySMTPContext (не isolated SMTP)."""
    if _SMTP_GLOBAL_PROXY_ACTIVE:
        return True
    try:
        if _HTTP_SMTP_PROXY_CTX.get() is not None:
            return True
    except Exception:
        pass
    try:
        import smtplib

        if smtplib.socket is not _SMTP_SOCKET_ORIG:
            return True
    except Exception:
        pass
    if _SOCKET_GETADDRINFO_ORIG is not None and _stdlib_socket.getaddrinfo is not _SOCKET_GETADDRINFO_ORIG:
        return True
    return False


async def _reset_socks_under_lock() -> None:
    """Короткий lock только на сброс PySocks (миллисекунды), не на весь запрос к Postgres."""
    if not smtp_global_proxy_is_active():
        return

    lock_wait = float(os.getenv("DB_SOCKET_LOCK_TIMEOUT_SEC", "2"))
    try:
        await asyncio.wait_for(_DB_SOCKET_LOCK.acquire(), timeout=lock_wait)
    except asyncio.TimeoutError:
        logger.error(
            "DB socket lock timeout (%.0fs) — reset без lock", lock_wait
        )
        reset_smtplib_proxy()
        return

    try:
        reset_smtplib_proxy()
    finally:
        _DB_SOCKET_LOCK.release()


@asynccontextmanager
async def database_socket_guard():
    """
    Перед/после работы с Postgres: сбросить PySocks-патч, если он активен.
    При isolated-рассылке патча нет — guard почти free (без lock/логов).
    """
    if not smtp_global_proxy_is_active():
        yield
        return
    await _reset_socks_under_lock()
    try:
        yield
    finally:
        if smtp_global_proxy_is_active():
            await _reset_socks_under_lock()


def reset_smtplib_proxy() -> None:
    global _SOCKET_GETADDRINFO_ORIG, _SMTP_GLOBAL_PROXY_ACTIVE

    import smtplib

    was_active = smtp_global_proxy_is_active()
    _HTTP_SMTP_PROXY_CTX.set(None)
    _SMTP_GLOBAL_PROXY_ACTIVE = False

    try:
        import socks  # type: ignore
        socks.set_default_proxy()
    except Exception:
        pass

    if _SOCKET_GETADDRINFO_ORIG is not None:
        _stdlib_socket.getaddrinfo = _SOCKET_GETADDRINFO_ORIG  # type: ignore[assignment]

    smtplib.socket = _SMTP_SOCKET_ORIG
    if was_active:
        logger.debug("SMTP proxy reset (smtplib only)")


class ProxySMTPContext:
    """async with ProxySMTPContext(proxy): ... SMTP send ..."""

    def __init__(self, proxy: Proxy):
        self.proxy = proxy
        self._guard_token = None

    async def __aenter__(self):
        from services.smtp_proxy_guard import smtp_proxy_guard_enter

        await _PROXY_LOCK.acquire()
        try:
            self._guard_token = smtp_proxy_guard_enter()
            apply_proxy_to_smtplib(self.proxy)
            logger.info(
                "ProxySMTPContext enter: %s %s:%s",
                proxy_type_name(self.proxy),
                self.proxy.host,
                self.proxy.port,
            )
        except Exception:
            _PROXY_LOCK.release()
            raise
        return self

    async def __aexit__(self, exc_type, exc, tb):
        from services.smtp_proxy_guard import smtp_proxy_guard_exit

        try:
            try:
                reset_smtplib_proxy()
            except Exception:
                pass
        finally:
            if self._guard_token is not None:
                try:
                    smtp_proxy_guard_exit(self._guard_token)
                except Exception:
                    pass
                self._guard_token = None
            try:
                _PROXY_LOCK.release()
            except Exception:
                pass
        return False
