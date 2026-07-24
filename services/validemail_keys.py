"""Глобальные ключи ValidEmail из config (для всех пользователей)."""

from __future__ import annotations

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
            min(32, int(getattr(config, "VALIDEMAIL_SELLER_PARALLEL_PER_KEY", 12) or 12)),
        )
    except (TypeError, ValueError):
        return 12


def domain_probe_wave_size() -> int:
    """После 1-го домена — параллельные «волны» по N доменов (приоритет сохраняется)."""
    try:
        return max(
            1,
            min(8, int(getattr(config, "VALIDEMAIL_DOMAIN_WAVE_SIZE", 4) or 4)),
        )
    except (TypeError, ValueError):
        return 4


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
        return min(total, 50)
    return min(max(2, per * n), 50)


def validation_concurrency_plan(num_keys: int) -> tuple[int, int]:
    """(лимит HTTP на один ключ, суммарный пул). Каждый ключ до per_key, если pool хватает."""
    n = max(1, num_keys)
    per = per_key_concurrency_limit()
    pool = validation_pool_size(n)
    if pool >= per * n:
        return per, per * n
    per_effective = max(1, pool // n)
    return per_effective, per_effective * n
