"""Глобальные ключи ValidEmail из config (для всех пользователей)."""

from __future__ import annotations

import os

from config import config


def keys_from_config() -> list[str]:
    return [str(k).strip() for k in (config.VALIDEMAIL_API_KEYS or []) if str(k).strip()]


def resolve_validemail_api_keys() -> list[str]:
    return keys_from_config()


def per_key_concurrency_limit() -> int:
    try:
        return max(1, min(64, int(getattr(config, "VALIDEMAIL_CONCURRENCY_PER_KEY", 40) or 40)))
    except (TypeError, ValueError):
        return 40


def seller_parallel_per_key() -> int:
    try:
        return max(
            1,
            min(32, int(getattr(config, "VALIDEMAIL_SELLER_PARALLEL_PER_KEY", 10) or 10)),
        )
    except (TypeError, ValueError):
        return 10


def seller_batch_size() -> int:
    raw = (os.getenv("VALIDEMAIL_SELLER_BATCH_SIZE") or "").strip()
    if not raw:
        n = len(keys_from_config())
        raw = "50" if n >= 4 else "30"
    try:
        return max(1, min(70, int(raw)))
    except (TypeError, ValueError):
        return 25


def seller_batch_pause_sec() -> float:
    raw = (os.getenv("VALIDEMAIL_SELLER_BATCH_PAUSE_SEC") or "0.05").strip()
    try:
        return max(0.0, min(15.0, float(raw)))
    except (TypeError, ValueError):
        return 1.0


def seller_validation_timeout_sec() -> float:
    raw = (os.getenv("VALIDEMAIL_SELLER_TIMEOUT_SEC") or "90").strip()
    try:
        return max(30.0, min(300.0, float(raw)))
    except (TypeError, ValueError):
        return 90.0


def domain_probe_wave_size() -> int:
    """После 1-го домена — параллельные «волны» по N доменов (приоритет сохраняется)."""
    try:
        return max(
            1,
            min(16, int(getattr(config, "VALIDEMAIL_DOMAIN_WAVE_SIZE", 4) or 4)),
        )
    except (TypeError, ValueError):
        return 4


def tail_domains_one_batch() -> bool:
    """Домены 2…N одним HTTP-батчем (быстро); 0 = только волнами по DOMAIN_WAVE_SIZE."""
    raw = (os.getenv("VALIDEMAIL_TAIL_BATCH_ALL") or "1").strip().lower()
    return raw not in ("0", "false", "no", "off")


def max_domains_per_seller() -> int:
    """0 = все домены из приоритета; иначе обрезка списка."""
    try:
        n = int(getattr(config, "VALIDEMAIL_MAX_DOMAINS_PROBE", 0) or 0)
    except (TypeError, ValueError):
        return 0
    return max(0, min(32, n))


def validation_pool_size(num_keys: int | None = None) -> int:
    """
    Суммарный параллелизм: до N ключей × VALIDEMAIL_CONCURRENCY_PER_KEY (по умолчанию 6).
    VALIDEMAIL_CONCURRENCY в .env — явный потолок/override.
    """
    n = max(1, int(num_keys or 0) or len(keys_from_config()) or 1)
    per = per_key_concurrency_limit()
    try:
        total = int(getattr(config, "VALIDEMAIL_CONCURRENCY", 0) or 0)
    except (TypeError, ValueError):
        total = 0
    if total >= 2:
        return total
    return max(2, per * n)


def validation_concurrency_plan(num_keys: int) -> tuple[int, int]:
    """(лимит HTTP на один ключ, суммарный пул). Каждый ключ до per_key, если pool хватает."""
    n = max(1, num_keys)
    per = per_key_concurrency_limit()
    pool = validation_pool_size(n)
    if pool >= per * n:
        return per, per * n
    per_effective = max(1, pool // n)
    return per_effective, per_effective * n


def global_inflight_cap(num_keys: int | None = None) -> int:
    """Суммарный in-flight HTTP: по умолчанию per_key × число ключей (5 ключей ≈ 120)."""
    n = max(1, int(num_keys or 0) or len(keys_from_config()) or 1)
    per = per_key_concurrency_limit()
    raw = (os.getenv("VALIDEMAIL_GLOBAL_INFLIGHT") or "").strip()
    if raw:
        try:
            return max(12, min(200, int(raw)))
        except (TypeError, ValueError):
            pass
    return max(24, min(180, per * n))


def max_locals_per_seller() -> int:
    """Сколько local-part пробовать на продавца (first.last, firstlast, f.last, …)."""
    raw = (os.getenv("VALIDEMAIL_MAX_LOCALS") or "4").strip()
    try:
        return max(1, min(6, int(raw)))
    except (TypeError, ValueError):
        return 4


def optional_tail_domain_count() -> int:
    """0 = все домены пользователя одним батчем. >0 только для длинных списков (env)."""
    raw = (os.getenv("VALIDEMAIL_OPTIONAL_TAIL_DOMAINS") or "0").strip()
    try:
        return max(0, min(8, int(raw)))
    except (TypeError, ValueError):
        return 0


def extra_local_max_domains() -> int:
    """0 = запасной local-part на всех доменах из приоритета пользователя."""
    raw = (os.getenv("VALIDEMAIL_EXTRA_LOCAL_MAX_DOMAINS") or "0").strip()
    try:
        return max(0, min(32, int(raw)))
    except (TypeError, ValueError):
        return 0
