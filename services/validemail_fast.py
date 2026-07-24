"""Параллельная проверка через validemail.co GET /api/v1/validate (Bearer, см. api-doc)."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass
from typing import Callable, Iterable

import aiohttp

logger = logging.getLogger(__name__)


@dataclass
class CacheItem:
    ok: bool
    ts: float
    raw: dict


# cache key includes URL to avoid mixing different providers/endpoints
_CACHE: dict[str, CacheItem] = {}
_CACHE_TTL_SEC = 60 * 60 * 6  # 6 часов

_TRANSIENT_REASONS = frozenset({"connection_error", "timeout"})
_TRANSIENT_HTTP = frozenset({408, 429, 500, 502, 503, 504})
_NO_RETRY_HTTP = frozenset({402, 403, 405})
_DEFINITIVE_BAD_REASONS = frozenset(
    {
        "invalid_smtp",
        "rejected",
        "invalid_format",
        "invalid_domain",
        "disposable",
    }
)

_SESSION: aiohttp.ClientSession | None = None
_KEY_SEMAPHORES: dict[str, asyncio.Semaphore] = {}
_KEY_SEM_LIMITS: dict[str, int] = {}
_GLOBAL_INFLIGHT: asyncio.Semaphore | None = None


def _global_inflight_sem() -> asyncio.Semaphore:
    global _GLOBAL_INFLIGHT
    if _GLOBAL_INFLIGHT is None:
        try:
            cap = max(8, min(80, int(os.getenv("VALIDEMAIL_GLOBAL_INFLIGHT", "36"))))
        except (TypeError, ValueError):
            cap = 36
        _GLOBAL_INFLIGHT = asyncio.Semaphore(cap)
    return _GLOBAL_INFLIGHT


def _semaphore_for_api_key(api_key: str, limit: int) -> asyncio.Semaphore:
    """Один общий лимит in-flight на ключ (5 ключей × 40 = не создавать sem на каждый batch)."""
    k = (api_key or "").strip()
    lim = max(1, int(limit))
    if k not in _KEY_SEMAPHORES or _KEY_SEM_LIMITS.get(k) != lim:
        _KEY_SEMAPHORES[k] = asyncio.Semaphore(lim)
        _KEY_SEM_LIMITS[k] = lim
    return _KEY_SEMAPHORES[k]


def _cache_key(url: str, email: str) -> str:
    u = (url or "").strip().lower()
    e = (email or "").strip().lower()
    return f"{u}::{e}"


def _cache_get(url: str, email: str) -> CacheItem | None:
    k = _cache_key(url, email)
    if not k.strip(":"):
        return None
    item = _CACHE.get(k)
    if not item:
        return None
    if time.time() - item.ts > _CACHE_TTL_SEC:
        _CACHE.pop(k, None)
        return None
    return item


def _cache_set(url: str, email: str, ok: bool, raw: dict) -> None:
    if not _should_cache_result(raw):
        return
    k = _cache_key(url, email)
    if not k.strip(":"):
        return
    _CACHE[k] = CacheItem(ok=bool(ok), ts=time.time(), raw=raw or {})


def _validemail_api_timeout() -> int:
    """Query param timeout (сервер SMTP), API: 2–30 с, default 4."""
    try:
        from config import config

        base = int(getattr(config, "VALIDEMAIL_API_TIMEOUT", 8))
    except Exception:
        try:
            base = int(os.getenv("VALIDEMAIL_API_TIMEOUT", "8"))
        except (TypeError, ValueError):
            base = 8
    return max(2, min(30, base))


def _validemail_max_retries() -> int:
    try:
        from config import config

        return max(1, min(5, int(getattr(config, "VALIDEMAIL_MAX_RETRIES", 3))))
    except Exception:
        try:
            return max(1, min(5, int(os.getenv("VALIDEMAIL_MAX_RETRIES", "3"))))
        except (TypeError, ValueError):
            return 3


def _is_transient_failure(raw: object) -> bool:
    """Сеть / rate limit / connection_error — можно повторить."""
    if not isinstance(raw, dict):
        return True
    if raw.get("error") is not None and not any(
        k in raw for k in ("status", "isDeliverable", "State", "IsValid", "score", "Score")
    ):
        return True
    try:
        st = int(raw.get("_http_status") or 0)
        if st in _NO_RETRY_HTTP:
            return False
        if st in _TRANSIENT_HTTP:
            return True
        if st in (401,):
            return True
    except (TypeError, ValueError):
        pass
    reason = str(raw.get("reason") or raw.get("Reason") or "").lower().strip()
    return reason in _TRANSIENT_REASONS


def _should_cache_result(raw: object) -> bool:
    """Не кэшируем таймауты и 429 — иначе «валидные» теряются на час."""
    return not _is_transient_failure(raw)


def _retry_delay_sec(attempt: int, raw: dict) -> float:
    ra = raw.get("_retry_after")
    if ra is not None:
        try:
            return min(30.0, max(0.3, float(ra)))
        except (TypeError, ValueError):
            pass
    try:
        st = int(raw.get("_http_status") or 0)
    except (TypeError, ValueError):
        st = 0
    if st == 429:
        return min(30.0, 1.0 * (2**attempt))
    return min(6.0, 0.35 * (2**attempt))


async def _get_session() -> aiohttp.ClientSession:
    global _SESSION
    if _SESSION and not _SESSION.closed:
        return _SESSION

    api_t = _validemail_api_timeout()
    total = max(20, api_t + 12)
    timeout = aiohttp.ClientTimeout(
        total=total, connect=8, sock_connect=8, sock_read=api_t + 8
    )
    connector = aiohttp.TCPConnector(limit=512, ttl_dns_cache=300)
    _SESSION = aiohttp.ClientSession(timeout=timeout, connector=connector)
    return _SESSION


async def close_validemail_session() -> None:
    global _SESSION
    if _SESSION and not _SESSION.closed:
        await _SESSION.close()
    _SESSION = None


def _validemail_strict_mode() -> bool:
    return (os.getenv("VALIDEMAIL_STRICT", "0") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _validemail_min_score() -> int:
    try:
        return max(50, min(100, int(os.getenv("VALIDEMAIL_MIN_SCORE", "75"))))
    except (TypeError, ValueError):
        return 75


_BAD_EMAIL_STATES = frozenset(
    {
        "undeliverable",
        "unknown",
        "risky",
        "invalid",
        "not deliverable",
        "disposable",
        "catch-all",
        "catchall",
        "unverified",
        "reject",
        "rejected",
    }
)

_GOOD_DELIVERABLE_REASONS = frozenset({"accepted", "other"})  # legacy, не используется для отсева


def _normalize_ok_v1(data: dict, *, strict: bool, min_score: int) -> bool:
    """validemail.co v1 — главный сигнал isDeliverable, без whitelist reason."""
    status = str(data.get("status") or "").lower().strip()
    reason = str(data.get("reason") or data.get("Reason") or "").lower().strip()

    if reason in _TRANSIENT_REASONS:
        return False
    if data.get("isDisposable") is True:
        return False
    if data.get("isFormatValid") is False or data.get("isDomainValid") is False:
        return False

    if data.get("isDeliverable") is True and status != "undeliverable":
        if strict:
            raw_sc = data.get("score") if data.get("score") is not None else data.get("Score")
            if raw_sc is not None:
                try:
                    if int(raw_sc) < min_score:
                        return False
                except (TypeError, ValueError):
                    pass
        return True

    if reason in _DEFINITIVE_BAD_REASONS:
        return False

    if status == "undeliverable":
        return False
    if status == "unknown":
        return False
    if status == "risky":
        if not (os.getenv("VALIDEMAIL_ACCEPT_RISKY") or "").strip().lower() in (
            "1",
            "true",
            "yes",
            "on",
        ):
            return False

    if status == "deliverable":
        if strict:
            raw_sc = data.get("score") if data.get("score") is not None else data.get("Score")
            if raw_sc is not None:
                try:
                    if int(raw_sc) < min_score:
                        return False
                except (TypeError, ValueError):
                    pass
        return True

    return False


def _normalize_ok(data: object) -> bool:
    """
    validemail.co API v1: status, reason, score, isDeliverable (см. api-doc).
    Плюс legacy PascalCase (IsValid, State, Score).
    """
    if not isinstance(data, dict):
        return False

    strict = _validemail_strict_mode()
    min_score = _validemail_min_score()

    status = str(
        data.get("status") or data.get("State") or data.get("state") or ""
    ).lower().strip()
    reason = str(data.get("reason") or data.get("Reason") or "").lower().strip()

    if reason in _TRANSIENT_REASONS:
        return False

    if "isDeliverable" in data and "status" in data:
        return _normalize_ok_v1(data, strict=strict, min_score=min_score)

    # --- legacy / PascalCase ---
    state = status
    if state in _BAD_EMAIL_STATES:
        return False

    # validemail.co / validemail.net (PascalCase, legacy)
    if data.get("IsValid") is True or data.get("isValid") is True:
        if strict and state in _BAD_EMAIL_STATES:
            return False
        return True
    if state in ("deliverable", "valid", "ok", "accepted"):
        return True

    reason = str(data.get("Reason") or data.get("reason") or "").lower()
    if "invalid" in reason or "undeliverable" in reason or "not deliverable" in reason:
        return False
    if not strict and "accepted" in reason:
        return True

    try:
        score = int(data.get("Score") if data.get("Score") is not None else data.get("score") or 0)
        if strict:
            if score >= min_score and state in ("deliverable", "valid", "ok", "accepted"):
                return True
        elif score >= 80 and state != "not deliverable":
            return True
    except (TypeError, ValueError):
        pass

    # lowercase / legacy
    if data.get("is_valid") is True or data.get("valid") is True:
        return True

    status = str(
        data.get("status") or data.get("result") or data.get("State") or ""
    ).lower().strip()
    if status in _BAD_EMAIL_STATES:
        return False
    if status in ("valid", "ok", "deliverable", "accepted"):
        return True

    if data.get("isDeliverable") is True or data.get("is_deliverable") is True or data.get("deliverable") is True:
        return True

    if not strict and data.get("smtp_check") is True:
        return True

    return False


def _build_request(url: str, api_key: str, email: str) -> tuple[dict, dict]:
    """
    Возвращает (headers, params) для GET запроса.
    Поддерживает:
      - validemail.co (Bearer, params email)
      - api.validemail.net (api_key query, params api_key+email)
      - auto по URL
    """
    u = (url or "").strip()
    ul = u.lower()
    headers: dict = {}
    params: dict = {}

    if "validemail.co" in ul:
        headers["Accept"] = "application/json"
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        params["email"] = email
        params["timeout"] = str(_validemail_api_timeout())
        return headers, params

    # default / legacy style (query api_key)
    params["api_key"] = api_key
    params["email"] = email
    return headers, params


ProgressCb = Callable[[int, int, int, int], None]


async def _fetch_validemail_once(
    email_lc: str,
    *,
    api_key: str,
    url: str,
    use_ssl_verify: bool,
) -> tuple[bool, dict]:
    s = await _get_session()
    headers, params = _build_request(url, api_key, email_lc)
    ssl = None if use_ssl_verify else False
    async with s.get(url, params=params, headers=headers, ssl=ssl) as r:
        status = int(r.status)
        try:
            data = await r.json(content_type=None)
        except Exception as e:
            data = {"error": str(e)}
        raw = data if isinstance(data, dict) else {"raw": str(data)}
        if isinstance(raw, dict):
            raw["_http_status"] = status
            ra = r.headers.get("Retry-After")
            if ra:
                raw["_retry_after"] = ra
            if status in _NO_RETRY_HTTP:
                raw["_api_key_error"] = True
                msg = raw.get("message") or raw.get("error") or raw.get("detail")
                if msg:
                    raw["_api_message"] = str(msg)
        if status != 200:
            return False, raw
        ok = _normalize_ok(raw)
        return ok, raw


async def _check_one(
    email: str,
    *,
    api_key: str,
    url: str,
    use_ssl_verify: bool,
    semaphore: asyncio.Semaphore,
    lock: asyncio.Lock,
    progress_cb: ProgressCb | None,
    counters: dict,
    limit: int,
) -> tuple[str, bool, dict]:
    email_lc = (email or "").strip().lower()
    if not email_lc:
        return email, False, {"error": "empty"}

    cached = _cache_get(url, email_lc)
    if cached:
        async with lock:
            counters["done"] += 1
            if progress_cb:
                try:
                    progress_cb(counters["done"], counters["total"], limit, counters["in_use"])
                except Exception:
                    pass
        return email, cached.ok, cached.raw

    max_attempts = _validemail_max_retries()
    last_raw: dict = {"error": "not_checked"}

    async with _global_inflight_sem():
        async with semaphore:
            async with lock:
                counters["in_use"] += 1
                if progress_cb:
                    try:
                        progress_cb(counters["done"], counters["total"], limit, counters["in_use"])
                    except Exception:
                        pass

            try:
                ok = False
                for attempt in range(max_attempts):
                    try:
                        ok, last_raw = await _fetch_validemail_once(
                            email_lc,
                            api_key=api_key,
                            url=url,
                            use_ssl_verify=use_ssl_verify,
                        )
                    except Exception as e:
                        last_raw = {"error": str(e)}
                        ok = False

                    if ok:
                        _cache_set(url, email_lc, True, last_raw)
                        return email, True, last_raw

                    if not _is_transient_failure(last_raw) or attempt >= max_attempts - 1:
                        if _should_cache_result(last_raw):
                            _cache_set(url, email_lc, False, last_raw)
                        return email, False, last_raw

                    if isinstance(last_raw, dict) and last_raw.get("_api_key_error"):
                        if _should_cache_result(last_raw):
                            _cache_set(url, email_lc, False, last_raw)
                        return email, False, last_raw

                    delay = _retry_delay_sec(attempt, last_raw)
                    logger.debug(
                        "validemail retry %s/%s for %s in %.1fs (%s)",
                        attempt + 2,
                        max_attempts,
                        email_lc,
                        delay,
                        last_raw.get("reason") or last_raw.get("error") or last_raw.get("_http_status"),
                    )
                    await asyncio.sleep(delay)

                return email, False, last_raw
            finally:
                async with lock:
                    counters["in_use"] -= 1
                    counters["done"] += 1
                    if progress_cb:
                        try:
                            progress_cb(counters["done"], counters["total"], limit, counters["in_use"])
                        except Exception:
                            pass


async def _validate_emails_single_key(
    emails_list: list[str],
    *,
    api_key: str,
    concurrency: int,
    url: str,
    use_ssl_verify: bool,
    progress_cb: ProgressCb | None,
    counters: dict | None = None,
    shared_limit: int | None = None,
) -> list[tuple[str, bool, dict]]:
    api_key = (api_key or "").strip()
    if not api_key:
        return [(e, False, {"error": "no api key"}) for e in emails_list]

    limit = max(2, int(concurrency))
    display_limit = int(shared_limit) if shared_limit is not None else limit
    sem = _semaphore_for_api_key(api_key, limit)
    lock = asyncio.Lock()

    local_counters = counters if counters is not None else {
        "done": 0,
        "in_use": 0,
        "total": len(emails_list),
    }
    if counters is None and progress_cb:
        try:
            progress_cb(0, local_counters["total"], display_limit, 0)
        except Exception:
            pass

    tasks = [
        asyncio.create_task(
            _check_one(
                e,
                api_key=api_key,
                url=url,
                use_ssl_verify=use_ssl_verify,
                semaphore=sem,
                lock=lock,
                progress_cb=progress_cb,
                counters=local_counters,
                limit=display_limit,
            )
        )
        for e in emails_list
    ]
    return await asyncio.gather(*tasks)


async def validate_emails_fast(
    emails: Iterable[str],
    *,
    api_key: str | None = None,
    api_keys: list[str] | None = None,
    concurrency: int = 25,
    url: str = "https://validemail.co/api/v1/validate",
    use_ssl_verify: bool = True,
    progress_cb: ProgressCb | None = None,
) -> list[tuple[str, bool, dict]]:
    """
    Быстрая параллельная проверка email.
    Несколько api_keys: emails делятся между ключами, каждый ключ — свой пул запросов.
  """
    url = (url or "").strip() or "https://validemail.co/api/v1/validate"
    emails_list = [str(e).strip() for e in emails if str(e).strip()]

    keys = [str(k).strip() for k in (api_keys or []) if str(k).strip()]
    if not keys:
        single = (api_key or "").strip()
        if single:
            keys = [single]

    if not keys:
        return [(e, False, {"error": "no api key"}) for e in emails_list]

    from services.validemail_keys import per_key_concurrency_limit, validation_concurrency_plan

    per_key_cap = per_key_concurrency_limit()

    if len(keys) == 1:
        single_limit = min(per_key_cap, max(2, int(concurrency)))
        return await _validate_emails_single_key(
            emails_list,
            api_key=keys[0],
            concurrency=single_limit,
            url=url,
            use_ssl_verify=use_ssl_verify,
            progress_cb=progress_cb,
        )

    n_keys = len(keys)
    per_key_limit, total_limit = validation_concurrency_plan(n_keys)
    if int(concurrency) > 0:
        per_key_limit = min(per_key_cap, max(2, int(concurrency) // n_keys))
        total_limit = per_key_limit * n_keys

    buckets: list[list[tuple[int, str]]] = [[] for _ in range(n_keys)]
    for i, e in enumerate(emails_list):
        buckets[i % n_keys].append((i, e))

    shared_counters = {"done": 0, "in_use": 0, "total": len(emails_list)}
    if progress_cb:
        try:
            progress_cb(0, shared_counters["total"], total_limit, 0)
        except Exception:
            pass

    async def _run_bucket(key_idx: int, bucket: list[tuple[int, str]]) -> list[tuple[int, str, bool, dict]]:
        if not bucket:
            return []
        emails_only = [e for _, e in bucket]
        rows = await _validate_emails_single_key(
            emails_only,
            api_key=keys[key_idx],
            concurrency=per_key_limit,
            url=url,
            use_ssl_verify=use_ssl_verify,
            progress_cb=progress_cb,
            counters=shared_counters,
            shared_limit=total_limit,
        )
        return [(bucket[i][0], rows[i][0], rows[i][1], rows[i][2]) for i in range(len(rows))]

    merged: list[tuple[str, bool, dict] | None] = [None] * len(emails_list)
    bucket_results = await asyncio.gather(*(_run_bucket(i, b) for i, b in enumerate(buckets)))
    for chunk in bucket_results:
        for orig_i, email, ok, raw in chunk:
            merged[orig_i] = (email, ok, raw)

    out: list[tuple[str, bool, dict]] = []
    for i, e in enumerate(emails_list):
        row = merged[i]
        if row is None:
            out.append((e, False, {"error": "not_checked"}))
        else:
            out.append(row)
    return out
