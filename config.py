import os
import re

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from region import TEAM_NAME


def _parse_validemail_api_keys() -> list[str]:
    """VALIDEMAIL_API_KEYS=a,b,c и/или VALIDEMAIL_API_KEY_1= … _32= (без дубликатов)."""
    seen: set[str] = set()
    out: list[str] = []

    def add(raw: str) -> None:
        k = (raw or "").strip()
        if not k or k in seen:
            return
        seen.add(k)
        out.append(k)

    bulk = (os.getenv("VALIDEMAIL_API_KEYS") or "").strip()
    if bulk:
        for part in re.split(r"[,;\n]+", bulk):
            add(part)

    add((os.getenv("VALIDEMAIL_API_KEY") or "").strip())

    for i in range(1, 33):
        add((os.getenv(f"VALIDEMAIL_API_KEY_{i}") or "").strip())

    return out


def _validemail_per_key_concurrency() -> int:
    raw = (os.getenv("VALIDEMAIL_CONCURRENCY_PER_KEY") or "20").strip()
    try:
        return max(1, min(64, int(raw)))
    except (TypeError, ValueError):
        return 40


def _validemail_seller_parallel_per_key() -> int:
    raw = (os.getenv("VALIDEMAIL_SELLER_PARALLEL_PER_KEY") or "14").strip()
    try:
        return max(1, min(32, int(raw)))
    except (TypeError, ValueError):
        return 12


def _validemail_domain_wave_size() -> int:
    raw = (os.getenv("VALIDEMAIL_DOMAIN_WAVE_SIZE") or "3").strip()
    try:
        return max(1, min(8, int(raw)))
    except (TypeError, ValueError):
        return 4


def _validemail_max_domains_probe() -> int:
    raw = (os.getenv("VALIDEMAIL_MAX_DOMAINS_PROBE") or "0").strip()
    try:
        return max(0, min(32, int(raw)))
    except (TypeError, ValueError):
        return 0


def _parse_admin_ids(raw: str) -> list[int]:
    out: list[int] = []
    for part in (raw or "").split(","):
        part = part.strip()
        if part.isdigit():
            out.append(int(part))
    return out


class Config:
    BOT_TOKEN = (os.getenv("BOT_TOKEN") or "").strip()

    _admins_env = os.getenv("ADMIN_IDS", "").strip()
    ADMIN_IDS = _parse_admin_ids(_admins_env) if _admins_env else []

    DATABASE_URL = (os.getenv("DATABASE_URL") or "").strip()

    VALIDEMAIL_URL = os.getenv("VALIDEMAIL_URL", "https://validemail.co/api/v1/validate").strip()
    VALIDEMAIL_API_KEYS = _parse_validemail_api_keys()
    VALIDEMAIL_CONCURRENCY_PER_KEY = _validemail_per_key_concurrency()
    VALIDEMAIL_SELLER_PARALLEL_PER_KEY = _validemail_seller_parallel_per_key()
    VALIDEMAIL_DOMAIN_WAVE_SIZE = _validemail_domain_wave_size()
    VALIDEMAIL_MAX_DOMAINS_PROBE = _validemail_max_domains_probe()
    _conc_env = (os.getenv("VALIDEMAIL_CONCURRENCY") or "").strip()
    if _conc_env.isdigit():
        VALIDEMAIL_CONCURRENCY = max(2, int(_conc_env))
    else:
        n_k = max(1, len(VALIDEMAIL_API_KEYS))
        VALIDEMAIL_CONCURRENCY = max(2, VALIDEMAIL_CONCURRENCY_PER_KEY * n_k)
    VALIDEMAIL_API_TIMEOUT = max(
        2,
        min(
            30,
            int(
                os.getenv(
                    "VALIDEMAIL_API_TIMEOUT",
                    "8" if (os.getenv("VALIDEMAIL_TRAFFIC_MODE") or "1").strip().lower()
                    not in ("0", "false", "no", "off")
                    else "6",
                )
            ),
        ),
    )
    VALIDEMAIL_MAX_RETRIES = max(1, min(5, int(os.getenv("VALIDEMAIL_MAX_RETRIES", "2"))))

    GLOBAL_SUBJECT_TEMPLATE = os.getenv("GLOBAL_SUBJECT_TEMPLATE", "Re: OFFER").strip() or "Re: OFFER"

    # GAG / APEX API — docs.domainforapi.com
    GAG_API_BASE = (
        os.getenv("GAG_API_BASE")
        or os.getenv("APEX_API_BASE")
        or os.getenv("GOO_API_BASE")
        or ""
    ).strip().rstrip("/")
    GAG_GENERATE_DOMAIN = int(os.getenv("GAG_GENERATE_DOMAIN", "1") or "1")
    GAG_LINK_VERSION = (os.getenv("GAG_LINK_VERSION", "lk") or "lk").strip() or "lk"
    GAG_BALANCE_CHECKER = (os.getenv("GAG_BALANCE_CHECKER", "0") or "0").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    TEAM_NAME = TEAM_NAME
    AQUA_DEFAULT_IMAGE_URL = (os.getenv("AQUA_DEFAULT_IMAGE_URL") or "").strip()
    COUNTRY_CODE = "CH"
    COUNTRY_LABEL = "Швейцария"

    DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "").strip()
    DEEPSEEK_API_BASE = (os.getenv("DEEPSEEK_API_BASE", "https://api.deepseek.com") or "").strip().rstrip("/")
    DEEPSEEK_MODEL = (os.getenv("DEEPSEEK_MODEL", "deepseek-chat") or "deepseek-chat").strip()
    TRANSLATE_PROVIDER = (os.getenv("TRANSLATE_PROVIDER", "auto") or "auto").strip().lower()


config = Config()
