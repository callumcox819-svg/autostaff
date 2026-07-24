"""Глобальные ключи ValidEmail из config (для всех пользователей)."""

from __future__ import annotations

from config import config


def keys_from_config() -> list[str]:
    return [str(k).strip() for k in (config.VALIDEMAIL_API_KEYS or []) if str(k).strip()]


def resolve_validemail_api_keys() -> list[str]:
    return keys_from_config()


def per_key_concurrency_limit() -> int:
    try:
        return max(1, min(12, int(getattr(config, "VALIDEMAIL_CONCURRENCY_PER_KEY", 6) or 6)))
    except (TypeError, ValueError):
        return 6


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
    """(лимит на один ключ, суммарный пул параллельных запросов)."""
    n = max(1, num_keys)
    per = per_key_concurrency_limit()
    pool = validation_pool_size(n)
    per_effective = min(per, max(1, pool // n))
    return per_effective, per_effective * n
