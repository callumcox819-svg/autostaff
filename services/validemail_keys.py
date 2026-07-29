"""Глобальные ключи ValidEmail из config (для всех пользователей)."""

from __future__ import annotations

import os

from config import config


def keys_from_config() -> list[str]:
    return [str(k).strip() for k in (config.VALIDEMAIL_API_KEYS or []) if str(k).strip()]


def resolve_validemail_api_keys() -> list[str]:
    return keys_from_config()


def validation_traffic_mode() -> bool:
    """Быстрый подбор: параллель без волн продавцов (VALIDEMAIL_TRAFFIC_MODE=1)."""
    raw = (os.getenv("VALIDEMAIL_TRAFFIC_MODE") or "1").strip().lower()
    return raw not in ("0", "false", "no", "off")


def validation_fast_mode() -> bool:
    """Цель ~2–4 мин на ~600 лотов (5 ключей): полный залп + высокий inflight."""
    raw = (os.getenv("VALIDEMAIL_FAST") or "").strip().lower()
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    return validation_traffic_mode()


def api_retry_max_sellers() -> int:
    """Повтор продавцов после transient API (0 = выкл)."""
    raw = (os.getenv("VALIDEMAIL_API_RETRY_MAX") or "").strip()
    if not raw:
        return 120 if validation_traffic_mode() else 0
    try:
        return max(0, min(120, int(raw)))
    except (TypeError, ValueError):
        return 0


def combined_local_probe() -> bool:
    """Все local-part × домены одним HTTP-залпом на продавца."""
    raw = (os.getenv("VALIDEMAIL_COMBINED_LOCALS") or "1").strip().lower()
    return raw not in ("0", "false", "no", "off")


def _env_int(name: str, *, default: int, traffic: int | None = None) -> int:
    raw = (os.getenv(name) or "").strip()
    if raw:
        try:
            return int(raw)
        except (TypeError, ValueError):
            pass
    if validation_traffic_mode() and traffic is not None:
        return traffic
    return default


def validemail_rps_per_key() -> float:
    """validemail.co api-doc: 10 req/s на ключ."""
    raw = (os.getenv("VALIDEMAIL_RPS_PER_KEY") or "10").strip()
    if raw in ("0", "off", "false", "no"):
        return 0.0
    try:
        return max(1.0, min(10.0, float(raw)))
    except (TypeError, ValueError):
        return 10.0


def per_key_concurrency_limit() -> int:
    try:
        base = int(getattr(config, "VALIDEMAIL_CONCURRENCY_PER_KEY", 40) or 40)
    except (TypeError, ValueError):
        base = 40
    if not (os.getenv("VALIDEMAIL_CONCURRENCY_PER_KEY") or "").strip():
        base = _env_int("VALIDEMAIL_CONCURRENCY_PER_KEY", default=base, traffic=22)
    cap = 28 if validation_fast_mode() else 12
    return max(1, min(cap, base))


def seller_parallel_per_key() -> int:
    raw = (os.getenv("VALIDEMAIL_SELLER_PARALLEL_PER_KEY") or "").strip()
    if raw:
        try:
            return max(1, min(32, int(raw)))
        except (TypeError, ValueError):
            pass
    n = _env_int("VALIDEMAIL_SELLER_PARALLEL_PER_KEY", default=14, traffic=16)
    return max(1, min(32, n))


def seller_batch_size() -> int:
    raw = (os.getenv("VALIDEMAIL_SELLER_BATCH_SIZE") or "").strip()
    if not raw:
        n = len(keys_from_config())
        raw = "120" if n >= 5 else ("80" if n >= 3 else "40")
    try:
        return max(1, min(150, int(raw)))
    except (TypeError, ValueError):
        return 25


def seller_batch_pause_sec() -> float:
    raw = (os.getenv("VALIDEMAIL_SELLER_BATCH_PAUSE_SEC") or "0").strip()
    try:
        return max(0.0, min(15.0, float(raw)))
    except (TypeError, ValueError):
        return 0.0


def seller_validation_timeout_sec() -> float:
    raw = (os.getenv("VALIDEMAIL_SELLER_TIMEOUT_SEC") or "").strip()
    if not raw:
        return 85.0 if validation_traffic_mode() else 120.0
    try:
        return max(30.0, min(300.0, float(raw)))
    except (TypeError, ValueError):
        return 90.0


def domain_probe_wave_size() -> int:
    try:
        return max(
            1,
            min(16, int(getattr(config, "VALIDEMAIL_DOMAIN_WAVE_SIZE", 4) or 4)),
        )
    except (TypeError, ValueError):
        return 4


def tail_domains_one_batch() -> bool:
    raw = (os.getenv("VALIDEMAIL_TAIL_BATCH_ALL") or "1").strip().lower()
    return raw not in ("0", "false", "no", "off")


def max_domains_per_seller() -> int:
    try:
        n = int(getattr(config, "VALIDEMAIL_MAX_DOMAINS_PROBE", 0) or 0)
    except (TypeError, ValueError):
        return 0
    return max(0, min(32, n))


def validation_pool_size(num_keys: int | None = None) -> int:
    """
    HTTP-пул ≈ ключи × per_key. VALIDEMAIL_CONCURRENCY=200 — потолок, не душим до 24.
    """
    n = max(1, int(num_keys or 0) or len(keys_from_config()) or 1)
    per = per_key_concurrency_limit()
    planned = max(2, per * n)
    try:
        cap = int(getattr(config, "VALIDEMAIL_CONCURRENCY", 0) or 0)
    except (TypeError, ValueError):
        cap = 0
    if cap >= 2:
        if cap < planned // 2:
            return planned
        return min(cap, planned) if cap >= planned else planned
    return planned


def validation_concurrency_plan(num_keys: int) -> tuple[int, int]:
    n = max(1, num_keys)
    per = per_key_concurrency_limit()
    pool = validation_pool_size(n)
    if pool >= per * n:
        return per, per * n
    per_effective = max(1, pool // n)
    return per_effective, per_effective * n


def global_inflight_cap(num_keys: int | None = None) -> int:
    n = max(1, int(num_keys or 0) or len(keys_from_config()) or 1)
    per = per_key_concurrency_limit()
    raw = (os.getenv("VALIDEMAIL_GLOBAL_INFLIGHT") or "").strip()
    if raw:
        try:
            return max(12, min(280, int(raw)))
        except (TypeError, ValueError):
            pass
    try:
        from_config = int(getattr(config, "VALIDEMAIL_GLOBAL_INFLIGHT", 0) or 0)
    except (TypeError, ValueError):
        from_config = 0
    if from_config >= 12:
        return from_config
    target = per * n * 5
    if validation_fast_mode():
        return max(120, min(240, target))
    return max(40, min(160, per * n * 3))


def combined_probe_max_emails() -> int:
    """Один залп local×domain на продавца (порядок = приоритет доменов)."""
    raw = (os.getenv("VALIDEMAIL_COMBINED_PROBE_MAX") or "").strip()
    if not raw:
        return 42 if validation_fast_mode() else 36
    try:
        return max(4, min(48, int(raw)))
    except (TypeError, ValueError):
        return 36


def quick_combined_probe_size() -> int:
    """0 = один полный залп (быстрее и не теряет хвост доменов). >0 = сначала N адресов."""
    raw = (os.getenv("VALIDEMAIL_QUICK_PROBE_SIZE") or "").strip()
    if not raw:
        return 0 if validation_fast_mode() else 0
    try:
        return max(0, min(36, int(raw)))
    except (TypeError, ValueError):
        return 12


def max_locals_per_seller() -> int:
    raw = (os.getenv("VALIDEMAIL_MAX_LOCALS") or "").strip()
    if not raw:
        raw = "6"
    try:
        return max(1, min(6, int(raw)))
    except (TypeError, ValueError):
        return 4


def domain_tiers_for_probe(domains: list[str]) -> list[list[str]]:
    clean = [str(d or "").strip().lower() for d in domains if str(d or "").strip()]
    return [clean] if clean else []


def domain_first_probe() -> bool:
    """
    Домены строго по «Приоритет отправки»: 1-й домен × все local-part,
    нашли — следующий продавец; нет — 2-й домен и т.д.
    """
    raw = (os.getenv("VALIDEMAIL_DOMAIN_FIRST") or "").strip().lower()
    if raw in ("0", "false", "no", "off"):
        return False
    if raw in ("1", "true", "yes", "on"):
        return True
    return validation_traffic_mode()


def probe_by_domain_waves() -> bool:
    """Legacy alias: включено вместе с domain_first или VALIDEMAIL_PROBE_BY_DOMAIN=1."""
    if not domain_first_probe():
        raw = (os.getenv("VALIDEMAIL_PROBE_BY_DOMAIN") or "0").strip().lower()
        return raw in ("1", "true", "yes", "on")
    return True


def probe_retry_count() -> int:
    raw = (os.getenv("VALIDEMAIL_PROBE_RETRIES") or "").strip()
    if not raw:
        return 1 if validation_traffic_mode() else 2
    try:
        return max(1, min(5, int(raw)))
    except (TypeError, ValueError):
        return 2


def optional_tail_domain_count() -> int:
    raw = (os.getenv("VALIDEMAIL_OPTIONAL_TAIL_DOMAINS") or "0").strip()
    try:
        return max(0, min(8, int(raw)))
    except (TypeError, ValueError):
        return 0


def extra_local_max_domains() -> int:
    raw = (os.getenv("VALIDEMAIL_EXTRA_LOCAL_MAX_DOMAINS") or "0").strip()
    try:
        return max(0, min(32, int(raw)))
    except (TypeError, ValueError):
        return 0
