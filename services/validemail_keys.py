"""Глобальные ключи ValidEmail / mailcheck из config (для всех пользователей)."""

from __future__ import annotations

import os

from config import config

# Свой SMTP-валидатор на Railway (ValidEmail-compatible API).
MAILCHECK_DEFAULT_URL = (
    "https://validator-production-7106.up.railway.app/api/v1/validate"
)
MAILCHECK_DUMMY_KEY = "mailcheck"


def is_mailcheck_style_url(url: str | None = None) -> bool:
    """Свой endpoint (Railway /api/v1/validate), не validemail.co/.net."""
    flag = (os.getenv("VALIDEMAIL_MAILCHECK") or "").strip().lower()
    if flag in ("1", "true", "yes", "on"):
        return True
    if flag in ("0", "false", "no", "off"):
        return False
    u = (url or os.getenv("VALIDEMAIL_URL") or getattr(config, "VALIDEMAIL_URL", "") or "").strip().lower()
    if not u:
        return False
    if "validemail.co" in u or "validemail.net" in u:
        return False
    if "railway.app" in u:
        return True
    return "/api/v1/validate" in u


def keys_from_config() -> list[str]:
    return [str(k).strip() for k in (config.VALIDEMAIL_API_KEYS or []) if str(k).strip()]


def resolve_validemail_api_keys() -> list[str]:
    keys = keys_from_config()
    if keys:
        return keys
    # mailcheck без API_KEY на сервере — нужен dummy только для пула семафоров.
    if is_mailcheck_style_url():
        return [MAILCHECK_DUMMY_KEY]
    return []


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
    """Второй круг по всем unknown. 0 = выкл (дефолт): 15 мин «Повтор после сбоев»."""
    raw = (os.getenv("VALIDEMAIL_API_RETRY_MAX") or "").strip()
    if not raw:
        return 0
    try:
        return max(-1, min(5000, int(raw)))
    except (TypeError, ValueError):
        return 0


def validation_wall_sec(num_keys: int | None = None) -> float:
    """Потолок всего прогона. Свой SMTP: до 180 с (2–3 мин). 0 = без обрыва (validemail.co)."""
    _ = num_keys
    raw = (os.getenv("VALIDEMAIL_DEADLINE_SEC") or "").strip()
    if raw:
        try:
            return max(0.0, min(180.0, float(raw)))
        except (TypeError, ValueError):
            pass
    if is_mailcheck_style_url():
        return 180.0
    return 0.0


def api_retry_wall_sec() -> float:
    raw = (os.getenv("VALIDEMAIL_API_RETRY_SEC") or "").strip()
    if raw:
        try:
            return max(0.0, min(300.0, float(raw)))
        except (TypeError, ValueError):
            pass
    return 40.0


def combined_local_probe() -> bool:
    """Все local-part × домены одним HTTP-залпом. Выкл по умолчанию — SMTP не успевает."""
    raw = (os.getenv("VALIDEMAIL_COMBINED_LOCALS") or "0").strip().lower()
    return raw in ("1", "true", "yes", "on")


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
    """validemail.co: 10 req/s. mailcheck: без RPS-лимита (0)."""
    raw = (os.getenv("VALIDEMAIL_RPS_PER_KEY") or "").strip()
    if raw in ("0", "off", "false", "no"):
        return 0.0
    if not raw:
        return 0.0 if is_mailcheck_style_url() else 10.0
    try:
        v = float(raw)
        if v <= 0:
            return 0.0
        return max(1.0, min(10.0, v)) if not is_mailcheck_style_url() else max(0.0, v)
    except (TypeError, ValueError):
        return 0.0 if is_mailcheck_style_url() else 10.0


def per_key_concurrency_limit() -> int:
    """N одновременных запросов на ключ. ValidEmail ≤10; mailcheck — выше."""
    raw = (os.getenv("VALIDEMAIL_CONCURRENCY_PER_KEY") or "").strip()
    mailcheck = is_mailcheck_style_url()
    ceiling = 64 if mailcheck else 10
    default = 40 if mailcheck else 10
    if raw:
        try:
            return max(1, min(ceiling, int(raw)))
        except (TypeError, ValueError):
            pass
    return default


def seller_parallel_per_key() -> int:
    """Сколько продавцов на ключ параллельно."""
    raw = (os.getenv("VALIDEMAIL_SELLER_PARALLEL_PER_KEY") or "").strip()
    mailcheck = is_mailcheck_style_url()
    ceiling = 48 if mailcheck else 10
    if raw:
        try:
            return max(1, min(ceiling, int(raw)))
        except (TypeError, ValueError):
            pass
    if mailcheck:
        return min(ceiling, 24)
    return per_key_concurrency_limit()


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
    if raw:
        try:
            return max(8.0, min(120.0, float(raw)))
        except (TypeError, ValueError):
            pass
    # Один продавец не должен съесть весь 2-мин прогон.
    return 20.0 if is_mailcheck_style_url() else 90.0


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
    """0 = весь приоритет из бота. Не режем список."""
    raw = (os.getenv("VALIDEMAIL_MAX_DOMAINS_PROBE") or "").strip()
    if not raw:
        return 0
    try:
        return max(0, min(32, int(raw)))
    except (TypeError, ValueError):
        return 0


def max_unknown_domains_per_seller() -> int:
    """Сколько доменов подряд с unknown, потом стоп. «Нет ящика» — список не режем."""
    raw = (os.getenv("VALIDEMAIL_MAX_UNKNOWN_DOMAINS") or "").strip()
    if not raw:
        return 4
    try:
        return max(1, min(16, int(raw)))
    except (TypeError, ValueError):
        return 4


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
    """Всегда ключи × N. Не режем 7 ключей общим потолком 32."""
    n = max(1, int(num_keys or 0) or len(keys_from_config()) or 1)
    return per_key_concurrency_limit() * n


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
        raw = "4"
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
        return 1
    try:
        return max(1, min(5, int(raw)))
    except (TypeError, ValueError):
        return 1


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
