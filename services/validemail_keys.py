"""Глобальные ключи ValidEmail / mailcheck из config (для всех пользователей)."""

from __future__ import annotations

import os

from config import config

# Свой SMTP-валидатор на Railway (ValidEmail-compatible API).
MAILCHECK_DEFAULT_URL = (
    "https://validator-production-7106.up.railway.app/api/v1/validate"
)
MAILCHECK_DUMMY_KEY = "mailcheck"
VALIDEMAIL_HARD_URL_DEFAULT = "https://validemail.co/api/v1/validate"

_DUMMY_KEYS = frozenset({"mailcheck", "none", "dummy"})

# CH/DE ISP: всегда validemail.co, даже если кто-то добавил их в EASY_DOMAINS.
_ALWAYS_HARD_DOMAINS = frozenset(
    {
        "gmx.ch",
        "gmx.de",
        "gmx.net",
        "gmx.at",
        "gmx.com",
        "web.de",
        "t-online.de",
        "online.de",
        "bluewin.ch",
        "bluemail.ch",
        "sunrise.ch",
        "hispeed.ch",
        "swisscom.ch",
    }
)


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


def _parse_key_list(raw: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for part in (raw or "").replace(";", ",").split(","):
        k = part.strip()
        if not k or k in seen:
            continue
        seen.add(k)
        out.append(k)
    return out


def hard_validation_url() -> str:
    """validemail.co для сложных доменов. Пусто только если нет hard-ключей."""
    explicit = (os.getenv("VALIDEMAIL_HARD_URL") or "").strip()
    if explicit:
        return explicit
    if _hard_keys_raw():
        return VALIDEMAIL_HARD_URL_DEFAULT
    return ""


def _is_dummy_key(k: str) -> bool:
    return (k or "").strip().lower() in _DUMMY_KEYS


def _hard_keys_raw() -> list[str]:
    """8 ключей validemail.co: HARD_* или настоящие VALIDEMAIL_API_KEYS (не mailcheck)."""
    out: list[str] = []
    seen: set[str] = set()

    def add(k: str) -> None:
        s = (k or "").strip()
        if not s or _is_dummy_key(s) or s in seen:
            return
        seen.add(s)
        out.append(s)

    for k in _parse_key_list(os.getenv("VALIDEMAIL_HARD_API_KEYS") or ""):
        add(k)
    add(os.getenv("VALIDEMAIL_HARD_API_KEY") or "")
    for i in range(1, 33):
        add(os.getenv(f"VALIDEMAIL_HARD_API_KEY_{i}") or "")
    if out:
        return out
    # В боте часто кладут 8 co-ключей в VALIDEMAIL_API_KEYS — их нельзя скармливать mailcheck.
    for k in keys_from_config():
        add(k)
    return out


def resolve_hard_api_keys() -> list[str]:
    """Ключи validemail.co для GMX/bluewin/sunrise и прочих hard-доменов."""
    return _hard_keys_raw()


def hard_backend_enabled() -> bool:
    return bool(hard_validation_url() and resolve_hard_api_keys())


def easy_validation_domains() -> frozenset[str]:
    """Лёгкие домены → наш mailcheck (все страны). Остальное при dual → validemail.co."""
    base = {
        "gmail.com",
        "googlemail.com",
        "icloud.com",
        "me.com",
        "mac.com",
    }
    extra = (os.getenv("VALIDEMAIL_EASY_DOMAINS") or "").strip().lower()
    if extra:
        for part in extra.replace(";", ",").split(","):
            d = part.strip().lstrip("@")
            if d:
                base.add(d)
    return frozenset(base)


def hard_validation_domains() -> frozenset[str]:
    """Явный список hard (дополняет правило «всё, что не easy»)."""
    extra = (os.getenv("VALIDEMAIL_HARD_DOMAINS") or "").strip().lower()
    out: set[str] = set()
    if extra:
        for part in extra.replace(";", ",").split(","):
            d = part.strip().lstrip("@")
            if d:
                out.add(d)
    return frozenset(out)


def is_easy_validation_domain(domain_or_email: str) -> bool:
    s = (domain_or_email or "").strip().lower()
    if "@" in s:
        s = s.rsplit("@", 1)[-1]
    return bool(s) and s in easy_validation_domains()


def is_hard_validation_domain(domain_or_email: str) -> bool:
    """GMX/bluewin/sunrise и прочие не-gmail → validemail.co; gmail/icloud → mailcheck."""
    if not hard_backend_enabled():
        return False
    s = (domain_or_email or "").strip().lower()
    if "@" in s:
        s = s.rsplit("@", 1)[-1]
    if not s:
        return False
    if s in _ALWAYS_HARD_DOMAINS or s.startswith("gmx."):
        return True
    extra_hard = hard_validation_domains()
    if s in extra_hard:
        return True
    if is_easy_validation_domain(s):
        return False
    return True


def resolve_validemail_api_keys() -> list[str]:
    """Ключи «лёгкого» бэкенда. При dual всегда mailcheck, не ключи validemail.co."""
    keys = keys_from_config()
    if hard_backend_enabled():
        easy = [k for k in keys if k.lower() in {"mailcheck", "none", "dummy"}]
        return easy or [MAILCHECK_DUMMY_KEY]
    if keys:
        return keys
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
    """Потолок всего прогона. 0 = без обрыва. Дефолт mailcheck ~5 мин — успеть всех продавцов."""
    _ = num_keys
    raw = (os.getenv("VALIDEMAIL_DEADLINE_SEC") or "").strip()
    if raw:
        try:
            return max(0.0, min(600.0, float(raw)))
        except (TypeError, ValueError):
            pass
    if is_mailcheck_style_url():
        return 300.0
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


def validemail_rps_per_key(url: str | None = None) -> float:
    """validemail.co: 10 req/s. mailcheck: без RPS-лимита (0)."""
    raw = (os.getenv("VALIDEMAIL_RPS_PER_KEY") or "").strip()
    if raw in ("0", "off", "false", "no"):
        return 0.0
    mailcheck = is_mailcheck_style_url(url)
    # Для hard URL (validemail.co) — всегда лимит co, даже если основной VALIDEMAIL_URL = mailcheck.
    u = (url or "").strip().lower()
    if u and ("validemail.co" in u):
        mailcheck = False
    if not raw:
        return 0.0 if mailcheck else 10.0
    try:
        v = float(raw)
        if v <= 0:
            return 0.0
        return max(1.0, min(10.0, v)) if not mailcheck else max(0.0, v)
    except (TypeError, ValueError):
        return 0.0 if mailcheck else 10.0


def per_key_concurrency_limit(url: str | None = None) -> int:
    """N одновременных запросов на ключ. ValidEmail ≤10; mailcheck — выше."""
    raw = (os.getenv("VALIDEMAIL_CONCURRENCY_PER_KEY") or "").strip()
    u = (url or "").strip().lower()
    mailcheck = is_mailcheck_style_url(url)
    if u and "validemail.co" in u:
        mailcheck = False
    ceiling = 64 if mailcheck else 10
    default = 40 if mailcheck else 10
    if raw and mailcheck:
        try:
            return max(1, min(ceiling, int(raw)))
        except (TypeError, ValueError):
            pass
    if raw and not mailcheck:
        # Не тащим mailcheck CONCURRENCY_PER_KEY=40 на co (там потолок 10).
        try:
            return max(1, min(10, int(raw))) if int(raw) <= 10 else 10
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


def seller_parallel_cap_for_run(easy_keys: int, hard_keys: int = 0) -> int:
    """Сколько продавцов гоняем параллельно (учитываем hard-ключи)."""
    n_easy = max(1, int(easy_keys or 1))
    n_hard = max(0, int(hard_keys or 0))
    per = seller_parallel_per_key()
    base = per * n_easy
    if n_hard:
        # co: 10 req/s на ключ × 8 ключей — больше продавцов в полёте
        base = max(base, min(180, 10 * n_hard + per))
    if validation_fast_mode():
        base = max(base, min(180, base + 16))
    return max(1, min(180, base))


def seller_validation_timeout_sec() -> float:
    raw = (os.getenv("VALIDEMAIL_SELLER_TIMEOUT_SEC") or "").strip()
    if raw:
        try:
            return max(8.0, min(120.0, float(raw)))
        except (TypeError, ValueError):
            pass
    # dual/hard: не держим продавца 45с на медленных ISP
    if hard_backend_enabled():
        return 35.0 if is_mailcheck_style_url() else 50.0
    return 45.0 if is_mailcheck_style_url() else 90.0


def gmx_domain_probe_timeout_sec() -> float:
    """Сколько ждать один GMX/ISP-домен, потом следующий в приоритете."""
    raw = (os.getenv("VALIDEMAIL_GMX_DOMAIN_TIMEOUT_SEC") or "").strip()
    if raw:
        try:
            return max(3.0, min(60.0, float(raw)))
        except (TypeError, ValueError):
            pass
    # На validemail.co нет смысла ждать 12с SMTP — режем волну быстрее.
    if hard_backend_enabled():
        return 6.0
    return 12.0


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
    """Сколько доменов подряд с unknown, потом стоп."""
    raw = (os.getenv("VALIDEMAIL_MAX_UNKNOWN_DOMAINS") or "").strip()
    if not raw:
        return 3 if validation_fast_mode() else 4
    try:
        return max(1, min(16, int(raw)))
    except (TypeError, ValueError):
        return 3 if validation_fast_mode() else 4


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
