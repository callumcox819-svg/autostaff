from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Optional

from aiogram import Bot
from sqlalchemy import select

from database import Session
from models import User
from services.validemail_fast import (
    validate_emails_fast,
    _DEFINITIVE_BAD_REASONS,
    _is_transient_failure,
    _retry_delay_sec,
)

_TRANSIENT_API_REASONS = frozenset({"connection_error", "timeout"})
from utils.ui_emoji import html_emoji
from services.seller_name import (
    MIN_NAME_TOKEN_LEN,
    MIN_SELLER_LETTERS,
    is_business_token,
    is_usable_single_local,
    normalize_seller_name,
    person_tokens_for_email,
    pick_handle_locals,
    pick_name_tokens,
    pick_name_tokens_for_email,
    seller_name_eligible_for_validation,
    seller_name_from_item,
    seller_name_too_short,
)

logger = logging.getLogger(__name__)

# Только пользовательский blacklist из настроек (не режем имена из JSON автоматически).
DEFAULT_VALIDEMAIL_URL = (
    "https://validator-production-7106.up.railway.app/api/v1/validate"
)


@dataclass
class ValidationConfig:
    validemail_api_key: str | None = None
    validemail_api_keys: list[str] | None = None
    validation_url: str = DEFAULT_VALIDEMAIL_URL

    concurrency: int = 12
    max_emails_per_seller: int = 1
    min_len: int = MIN_NAME_TOKEN_LEN
    max_len: int = 40
    require_first_and_last: bool = False

    user_blacklist: list[str] | None = None
    use_ssl_verify: bool = True
    # Личный ЧС имён продавцов (Maria Johansen и т.д.) — повторно не валидировать
    seller_name_keys: set[str] | None = None
    # Уже есть OfferEmail — не гоняем API, это не ЧС
    already_validated_names: set[str] | None = None


# -------------------------
# Helpers: name normalization
# -------------------------

def classify_json_seller_skip(
    name_key: str,
    *,
    blacklist: set[str],
    already_validated: set[str],
    batch_seen: set[str],
) -> str | None:
    """Почему продавца не гоняем в API. «already_in_db» — не ЧС."""
    k = (name_key or "").strip().lower()
    if not k:
        return None
    if k in blacklist:
        return "blacklisted"
    if k in already_validated:
        return "already_in_db"
    if k in batch_seen:
        return "duplicates"
    return None


def _normalize_name(raw: str) -> str:
    return normalize_seller_name(raw)


def _pick_alpha_tokens(name: str) -> list[str]:
    return pick_name_tokens_for_email(name)


def _pick_first_last_alpha_tokens(name: str) -> tuple[str, str]:
    tokens = _pick_alpha_tokens(name)
    if len(tokens) < 2:
        return "", ""
    return tokens[0], tokens[-1]


def _name_is_usable(name: str, *, require_first_and_last: bool) -> bool:
    if seller_name_too_short(name):
        return False
    if pick_handle_locals(name):
        return not require_first_and_last
    if not seller_name_eligible_for_validation(name):
        return False
    tokens = _pick_alpha_tokens(name)
    if require_first_and_last:
        return len(tokens) >= 2
    return len(tokens) >= 1


def _name_has_first_last(name: str) -> bool:
    return _name_is_usable(name, require_first_and_last=True)


def _make_local_part_from_name(name: str, *, require_first_and_last: bool) -> str:
    """Один основной local-part (first.last или одно слово)."""
    variants = _make_local_part_variants(name, require_first_and_last=require_first_and_last)
    return variants[0] if variants else ""


def _make_local_part_variants(name: str, *, require_first_and_last: bool) -> list[str]:
    """
    Логины: Maria Johansen → maria.johansen / mariajohansen; ник mariasto2 → mariasto2.
    Без голых maria@/henk@ и без shop-слов (specialist@, juweliers@).
    """
    out: list[str] = []
    seen: set[str] = set()
    norm = _normalize_name(name)
    parts = [p for p in re.split(r"[\s\-']+", norm) if p.strip()]

    def _add(local: str) -> None:
        local = re.sub(r"[^a-z0-9._+\-_]", "", (local or "").lower())
        local = re.sub(r"\.+", ".", local).strip(".")
        if not local or local in seen:
            return
        if "." not in local and "_" not in local and "+" not in local:
            if not is_usable_single_local(local):
                return
        else:
            # составной: обе стороны не должны быть чисто business
            chunks = re.split(r"[._]", local)
            if chunks and all(is_business_token(c) for c in chunks if c):
                return
        seen.add(local)
        out.append(local)

    handles = pick_handle_locals(name)
    if handles and len(parts) <= 1:
        for h in handles:
            _add(h)
        return out

    tokens = person_tokens_for_email(name)
    if require_first_and_last and len(tokens) < 2:
        for h in handles:
            _add(h)
        return out
    if not tokens:
        for h in handles:
            _add(h)
        return out

    if len(tokens) == 1:
        for h in handles:
            _add(h)
        _add(tokens[0])
        return out

    first, last = tokens[0], tokens[-1]
    if len(first) < 1 or len(last) < 1:
        return out

    for h in handles:
        _add(h)
    # Только надёжные составные — SMTP меньше врёт
    _add(f"{first}.{last}")
    _add(f"{first}{last}")
    if len(first) >= 2 and len(last) >= 3:
        _add(f"{first[0]}.{last}")
        _add(f"{first[0]}{last}")
    return out


def _is_blacklisted(name: str, user_blacklist: Iterable[str] | None) -> bool:
    """Только явный blacklist пользователя (полное имя)."""
    if not name or not user_blacklist:
        return False
    n = _normalize_name(name).lower()
    for b in user_blacklist:
        bb = str(b or "").strip().lower()
        if bb and bb == n:
            return True
    return False


def _len_for_limits(local_part: str) -> int:
    return len((local_part or "").replace(".", ""))


def _is_cancelled_raw(raw: object) -> bool:
    return isinstance(raw, dict) and (
        raw.get("_cancelled") is True or str(raw.get("error") or "").lower() == "cancelled"
    )


def _is_api_failure(_ok: bool, raw: object) -> bool:
    """Сбой API/сети. Ответ «ящик не существует» (HTTP 200 / undeliverable) — не ошибка."""
    if _ok:
        return False
    if _is_cancelled_raw(raw):
        return False
    if not isinstance(raw, dict):
        return True
    try:
        st = int(raw.get("_http_status") or 0)
    except (TypeError, ValueError):
        st = 0

    reason = str(raw.get("reason") or raw.get("Reason") or "").lower().strip()

    if st == 200:
        if reason in _TRANSIENT_API_REASONS:
            return True
        status200 = str(
            raw.get("status") or raw.get("State") or raw.get("state") or ""
        ).lower().strip()
        # unknown = SMTP не ответил (не «ящика нет»). Иначе 300+ «без email» при 7 найденных.
        if status200 == "unknown":
            return True
        return False

    if reason in ("connection_error", "timeout"):
        return True
    if reason in _DEFINITIVE_BAD_REASONS:
        return False

    status = str(raw.get("status") or raw.get("State") or raw.get("state") or "").lower().strip()
    if status in (
        "deliverable",
        "undeliverable",
        "risky",
        "invalid",
        "not deliverable",
    ):
        return False
    if any(k in raw for k in ("isDeliverable", "IsValid", "isValid", "score", "Score")):
        return False

    if raw.get("_api_key_error"):
        return True
    if st in (401, 403, 402, 429) or st >= 500:
        return True

    err = raw.get("error")
    if err is None:
        err = raw.get("message")
    if err is not None:
        es = str(err or "").strip().lower()
        if es in ("", "empty", "no api key"):
            return False
        benign = (
            "invalid email",
            "not valid",
            "undeliverable",
            "not deliverable",
            "does not exist",
            "doesn't exist",
            "no mx",
            "mailbox",
            "rejected",
            "disposable",
            "unverified",
            "unknown user",
            "user unknown",
            "address not found",
            "no such user",
        )
        if any(p in es for p in benign):
            return False
        if any(
            x in es
            for x in (
                "timeout",
                "connect",
                "connection",
                "clientconnector",
                "rate limit",
                "too many",
                "429",
                "402",
                "403",
                "401",
                "500",
                "502",
                "503",
                "504",
            )
        ):
            return True
        return False

    return False


def _probe_inconclusive(ok: bool, raw: object) -> bool:
    """Таймаут/429/сеть/unknown/cancelled — не «ящик не существует»."""
    if ok:
        return False
    if _is_cancelled_raw(raw):
        return True
    if _is_api_failure(ok, raw):
        return True
    return _is_transient_failure(raw)


def _domain_wave_verdict(
    results: list[tuple[str, bool, dict]],
    pending: list[str],
) -> str:
    """hit — есть ящик; no — все undeliverable (берём следующий домен); unknown — SMTP не ответил."""
    by_lc = {(e or "").strip().lower(): (e, ok, raw) for e, ok, raw in results}
    inconclusive = 0
    definitive_no = 0
    for em in pending:
        em_lc = (em or "").strip().lower()
        row = by_lc.get(em_lc)
        if not row:
            inconclusive += 1
            continue
        _e, ok, raw = row
        if ok:
            return "hit"
        if _probe_inconclusive(ok, raw):
            inconclusive += 1
        else:
            definitive_no += 1
    if inconclusive > 0:
        return "unknown"
    return "no"


def _wave_seller_needs_api_retry(
    results: list[tuple[str, bool, dict]],
    priority_emails: list[str],
    *,
    seller_already_found: bool,
) -> bool:
    """Повтор, если остались timeout/unknown/cancelled — даже рядом с undeliverable."""
    if seller_already_found:
        return False
    by_lc = {(e or "").strip().lower(): (e, ok, raw) for e, ok, raw in results}
    definitive_no = 0
    inconclusive = 0
    for em_lc in priority_emails:
        em_lc = (em_lc or "").strip().lower()
        row = by_lc.get(em_lc)
        if not row:
            inconclusive += 1
            continue
        _e, ok, raw = row
        if ok:
            return False
        if _probe_inconclusive(ok, raw):
            inconclusive += 1
        else:
            definitive_no += 1
    # Есть не дожатые адреса — повторяем их, даже если соседний local уже undeliverable.
    return inconclusive > 0


def _should_retry_same_domain(ok: bool, raw: object) -> bool:
    """Только 429/сеть. HTTP 200 unknown — это ответ ValidEmail, берём следующий домен."""
    if ok:
        return False
    if isinstance(raw, dict) and raw.get("_api_key_error"):
        return False
    if isinstance(raw, dict):
        try:
            st = int(raw.get("_http_status") or 0)
        except (TypeError, ValueError):
            st = 0
        if st == 200:
            return False
    return _is_transient_failure(raw)


def _probe_max_attempts() -> int:
    from services.validemail_keys import probe_retry_count

    return probe_retry_count()


# -------------------------
# NEW API helpers (/validate)
# -------------------------

def _extract_emails_from_offer(offer: dict[str, Any]) -> list[str]:
    out: list[str] = []
    keys_direct = (
        "emails",
        "email",
        "seller_email",
        "from_email",
        "contact_email",
        "mail",
        "valid_email",
        "validated_email",
        "item_email",
    )

    def _collect_from(obj: dict[str, Any]) -> None:
        if not isinstance(obj, dict):
            return
        for key in keys_direct:
            if key not in obj:
                continue
            v = obj.get(key)
            if isinstance(v, str):
                e = v.strip()
                if e and "@" in e:
                    out.append(e)
            elif isinstance(v, list):
                for x in v:
                    if isinstance(x, str):
                        e = x.strip()
                        if e and "@" in e:
                            out.append(e)
                    elif isinstance(x, dict):
                        ev = x.get("email") or x.get("address")
                        if isinstance(ev, str) and "@" in ev.strip():
                            out.append(ev.strip())
            elif isinstance(v, dict):
                ev = v.get("email") or v.get("address")
                if isinstance(ev, str) and "@" in ev.strip():
                    out.append(ev.strip())
        void = obj.get("void")
        if isinstance(void, dict):
            _collect_from(void)
        data = obj.get("data")
        if isinstance(data, dict):
            _collect_from(data)

    _collect_from(offer)

    seen = set()
    uniq: list[str] = []
    for e in out:
        el = e.lower()
        if el not in seen:
            seen.add(el)
            uniq.append(e)
    return uniq


async def _get_validemail_key_for_user(session: Session, telegram_id: int) -> str | None:
    user = (await session.execute(select(User).where(User.telegram_id == int(telegram_id)))).scalars().first()
    if not user:
        return None
    key = (getattr(user, "validemail_key", None) or "").strip()
    return key or None


# -------------------------
# OLD API (handlers/validation.py) — УСКОРЕННЫЙ
# -------------------------

ProgressCb = Callable[[int, int, int, int], None]


def _domain_priority_waves(
    locals_list: list[str],
    domains_clean: list[str],
) -> list[tuple[str, list[str]]]:
    """Один домен за раз по приоритету: нашли email — вызывающий код не берёт следующий."""
    waves: list[tuple[str, list[str]]] = []
    seen: set[str] = set()
    for dom in domains_clean:
        dd = (dom or "").strip().lower()
        if not dd:
            continue
        wave: list[str] = []
        for loc in locals_list:
            loc = (loc or "").strip().lower()
            if not loc:
                continue
            em = f"{loc}@{dd}"
            if em in seen:
                continue
            seen.add(em)
            wave.append(em)
        if wave:
            waves.append((dd, wave))
    return waves


def merge_validation_domains(user_domains: list[str]) -> list[str]:
    """
    Домены в порядке «Приоритет отправки» (настройки) + остальные из БД, без дублей.
    Никакого принудительного gmail — только ваш список.
    """
    seen: set[str] = set()
    out: list[str] = []
    for d in user_domains or []:
        dd = str(d or "").strip().lower()
        if dd and dd not in seen:
            seen.add(dd)
            out.append(dd)
    return out


async def _validate_offers_old(
    items: list[dict[str, Any]],
    domains: list[str],
    cfg: ValidationConfig,
    *,
    progress_cb: ProgressCb | None = None,
    stats: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    # домены: uniq + clean (сохраняем порядок = приоритет)
    domains_clean: list[str] = []
    seen_dom = set()
    for d in domains or []:
        dd = str(d or "").strip().lower()
        if dd and dd not in seen_dom:
            seen_dom.add(dd)
            domains_clean.append(dd)
    if not domains_clean:
        return []

    user_blacklist = cfg.user_blacklist or []
    require_fl = bool(cfg.require_first_and_last)

    if stats is not None:
        _preserve = {
            k: stats[k]
            for k in (
                "validemail_keys",
                "validemail_pool",
                "validemail_per_key",
                "validemail_threads",
                "traffic_mode",
                "validation_t0",
            )
            if k in stats
        }
        stats.clear()
        stats.update(
            {
                "offers_total": len(items),
                "offers_eligible": 0,
                "offers_validated": 0,
                "offers_remaining": len(items),
                "emails_checked": 0,
                "emails_total": 0,
                "combinations_valid": 0,
                "current_domain": "",
                "sellers_with_email": 0,
                "last_valid_email": "",
                "seller_index": 0,
                "sellers_total": 0,
                "current_seller_name": "",
                "current_probe": "",
                "short_nicks": 0,
                "blacklisted": 0,
                "already_in_db": 0,
                "duplicates": 0,
                "api_errors": 0,
                "no_name": 0,
                "cache_negative_hits": 0,
            }
        )
        stats.update(_preserve)

    from services.validemail_fast import reset_validemail_runtime

    reset_validemail_runtime()
    if (os.getenv("VALIDEMAIL_CLEAR_CACHE") or "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    ):
        from services.validemail_fast import clear_validation_email_cache

        cleared = clear_validation_email_cache()
        if stats is not None and cleared:
            stats["cache_cleared"] = cleared

    from services.seller_blacklist import seller_name_key

    seller_bl = set(cfg.seller_name_keys or set())
    already_validated = set(cfg.already_validated_names or set())
    batch_seen_names: set[str] = set()
    pending_seller_names: set[str] = set()
    if stats is not None:
        stats["pending_seller_names"] = pending_seller_names

    # 1) Только имя из JSON → local-part → name@domain (готовых email в файле нет)
    prepared: list[dict[str, Any]] = []
    for it in items:
        if not isinstance(it, dict):
            continue

        raw_name = seller_name_from_item(it)
        if not (raw_name or "").strip():
            if stats is not None:
                stats["no_name"] = int(stats.get("no_name") or 0) + 1
            continue

        name_key = seller_name_key(raw_name)
        skip_why = classify_json_seller_skip(
            name_key,
            blacklist=seller_bl,
            already_validated=already_validated,
            batch_seen=batch_seen_names,
        )
        if skip_why and stats is not None:
            stats[skip_why] = int(stats.get(skip_why) or 0) + 1
        if skip_why:
            continue

        if _is_blacklisted(raw_name, user_blacklist):
            if stats is not None:
                stats["blacklisted"] = int(stats.get("blacklisted") or 0) + 1
            continue

        if not _name_is_usable(raw_name, require_first_and_last=require_fl):
            if stats is not None:
                stats["short_nicks"] = int(stats.get("short_nicks") or 0) + 1
            continue

        locals_list: list[str] = []
        for local in _make_local_part_variants(raw_name, require_first_and_last=require_fl):
            ln = _len_for_limits(local)
            min_local = MIN_SELLER_LETTERS if pick_handle_locals(raw_name) else int(cfg.min_len)
            if min_local <= ln <= int(cfg.max_len):
                locals_list.append(local)

        if not locals_list:
            if stats is not None:
                stats["short_nicks"] = int(stats.get("short_nicks") or 0) + 1
            continue

        prepared.append({
            "raw": it,
            "person_name": raw_name,
            "name_key": name_key,
            "locals": locals_list,
            "title": str(it.get("item_title") or it.get("title") or "").strip(),
            "price": str(it.get("item_price") or it.get("price") or "").strip(),
            "link": str(it.get("item_link") or it.get("link") or it.get("url") or "").strip(),
            "photo": str(it.get("item_photo") or it.get("photo") or it.get("image") or "").strip(),
        })
        if name_key:
            batch_seen_names.add(name_key)

    if stats is not None:
        stats["offers_eligible"] = len(prepared)
        stats["offers_remaining"] = max(0, int(stats.get("offers_total", 0)) - 0)

    if not prepared:
        return []

    # Одна валидная почта на продавца → сохраняем лот и идём дальше (без путаницы в AQUA/ответах).
    per_seller_limit = 1

    # хранит найденные валидные emails по индексу prepared
    found_by_idx: list[list[str]] = [[] for _ in prepared]

    # оценка проверок: сначала 1 логин × домен, потом запасные варианты
    n_dom = len(domains_clean)
    overall_total = max(
        1,
        sum(
            n_dom * max(1, len(p.get("locals") or []))
            for p in prepared
        ),
    )
    overall_done = 0

    if stats is not None:
        stats["emails_total"] = overall_total

    api_keys = [str(k).strip() for k in (cfg.validemail_api_keys or []) if str(k).strip()]
    if not api_keys:
        single = str(cfg.validemail_api_key or "").strip()
        if single:
            api_keys = [single]
    url = str(cfg.validation_url or DEFAULT_VALIDEMAIL_URL).strip()

    from services.validemail_keys import (
        combined_local_probe,
        max_domains_per_seller,
        max_unknown_domains_per_seller,
        max_locals_per_seller,
        probe_by_domain_waves,
        seller_batch_pause_sec,
        seller_batch_size,
        seller_parallel_per_key,
        seller_validation_timeout_sec,
        validation_concurrency_plan,
        global_inflight_cap,
        validation_traffic_mode,
        validation_fast_mode,
        domain_first_probe,
    )

    dom_cap = max_domains_per_seller()
    if dom_cap > 0:
        domains_clean = domains_clean[:dom_cap]

    n_keys = max(1, len(api_keys))
    per_key_limit, parallel_pool = validation_concurrency_plan(n_keys)
    sellers_parallel = seller_parallel_per_key()
    parallel_pool = global_inflight_cap(n_keys)

    if progress_cb:
        try:
            progress_cb(0, overall_total, parallel_pool, 0)
        except Exception:
            pass

    seen_valid_emails: set[str] = set()
    state_lock = asyncio.Lock()
    sellers_completed = 0
    seller_api_fail: list[int] = [0] * len(prepared)

    if stats is not None:
        stats["validemail_keys"] = n_keys
        stats["validemail_per_key"] = per_key_limit
        stats["validemail_threads"] = n_keys
        stats["validemail_pool"] = parallel_pool
        stats["domains_count"] = len(domains_clean)
        stats["max_locals"] = max_locals_per_seller()
        stats["traffic_mode"] = validation_traffic_mode()
        stats["domain_first"] = domain_first_probe()
        stats["combined_local_probe"] = combined_local_probe()
        stats["validation_fast"] = validation_fast_mode()
        if domains_clean:
            stats["priority_domains"] = domains_clean[:8]
        try:
            from config import config as _cfg

            stats["validemail_api_timeout"] = int(getattr(_cfg, "VALIDEMAIL_API_TIMEOUT", 8))
        except Exception:
            stats["validemail_api_timeout"] = 8

    logger.info(
        "validemail start: keys=%s pool=%s per_key=%s sellers=%s domains=%s order=%s domain_first=%s",
        n_keys,
        parallel_pool,
        per_key_limit,
        len(prepared),
        len(domains_clean),
        domains_clean[:6],
        domain_first_probe(),
    )

    logger.info(
        "validemail: keys=%s × %s req/key pool=%s batch=%s pause=%.2fs sellers=%s domains=%s traffic=%s combined_locals=%s",
        n_keys,
        per_key_limit,
        parallel_pool,
        seller_batch_size(),
        seller_batch_pause_sec(),
        len(prepared),
        len(domains_clean),
        validation_traffic_mode(),
        combined_local_probe(),
    )

    if n_keys >= 2:
        logger.info(
            "validemail: parallel sellers cap≈%s (×%s keys)",
            min(seller_batch_size(), sellers_parallel * n_keys),
            n_keys,
        )

    async def _run_batch(
        batch_emails: list[str],
        *,
        seller_i: int,
        dom: str,
        api_key: str,
        stop_on_first_ok: bool = False,
    ) -> list[tuple[str, bool, dict]]:
        if not batch_emails:
            return []
        async with state_lock:
            if stats is not None:
                stats["current_domain"] = dom
                stats["current_probe"] = batch_emails[0]
            base_done = overall_done

        def _wrap_progress(
            done: int, total: int, lim: int, in_use: int, _bd: int = base_done
        ) -> None:
            if not progress_cb:
                return
            try:
                progress_cb(_bd + int(done or 0), overall_total, parallel_pool, in_use)
            except Exception:
                pass

        use_keys = [api_key]
        use_stop = bool(stop_on_first_ok) and len(batch_emails) >= 2
        return await validate_emails_fast(
            batch_emails,
            api_keys=use_keys,
            concurrency=per_key_limit,
            url=url,
            use_ssl_verify=bool(cfg.use_ssl_verify),
            progress_cb=lambda d, t, l, u, _bd=base_done: _wrap_progress(d, t, l, u, _bd),
            stop_on_first_ok=use_stop,
        )

    async def _consume_results(
        seller_i: int,
        results: list[tuple[str, bool, dict]],
        *,
        count_api_errors: bool = True,
    ) -> int:
        nonlocal overall_done
        async with state_lock:
            checked = sum(
                1 for _e, _ok, raw in results if not _is_cancelled_raw(raw)
            )
            overall_done += checked
            combos_valid = 0
            for _e, ok, raw in results:
                if len(found_by_idx[seller_i]) >= per_seller_limit:
                    break
                if not ok:
                    if count_api_errors and stats is not None and _is_api_failure(ok, raw):
                        if seller_api_fail[seller_i] == 0:
                            stats["api_errors"] = int(stats.get("api_errors") or 0) + 1
                        seller_api_fail[seller_i] = 1
                    continue
                combos_valid += 1
                key = (_e or "").strip().lower()
                lst = found_by_idx[seller_i]
                if len(lst) >= per_seller_limit or key in lst:
                    continue
                if key in seen_valid_emails:
                    if stats is not None:
                        stats["duplicates"] = int(stats.get("duplicates") or 0) + 1
                    continue
                seen_valid_emails.add(key)
                lst.append(key)
                if stats is not None:
                    stats["last_valid_email"] = key
                if len(lst) >= per_seller_limit:
                    break
            return combos_valid

    def _refresh_stats() -> None:
        if stats is None:
            return
        sellers_found = sum(1 for f in found_by_idx if f)
        stats["emails_checked"] = overall_done
        stats["sellers_with_email"] = sellers_found
        stats["offers_validated"] = sellers_found
        eligible_o = int(stats.get("offers_eligible") or len(prepared))
        stats["offers_remaining"] = max(0, eligible_o - sellers_found)

    async def _consume_wave_priority(
        seller_i: int,
        results: list[tuple[str, bool, dict]],
        priority_emails: list[str],
        *,
        count_api_errors: bool = True,
    ) -> int:
        nonlocal overall_done
        by_lc: dict[str, tuple[str, bool, dict]] = {}
        for e, ok, raw in results:
            by_lc[(e or "").strip().lower()] = (e, ok, raw)

        async with state_lock:
            checked = sum(
                1 for _e, _ok, raw in results if not _is_cancelled_raw(raw)
            )
            overall_done += checked
            combos_valid = 0
            for em_lc in priority_emails:
                em_lc = (em_lc or "").strip().lower()
                row = by_lc.get(em_lc)
                if not row:
                    continue
                _e, ok, raw = row
                if len(found_by_idx[seller_i]) >= per_seller_limit:
                    break
                if not ok:
                    continue
                combos_valid += 1
                key = (_e or "").strip().lower()
                lst = found_by_idx[seller_i]
                if len(lst) >= per_seller_limit or key in lst:
                    continue
                if key in seen_valid_emails:
                    if stats is not None:
                        stats["duplicates"] = int(stats.get("duplicates") or 0) + 1
                    continue
                seen_valid_emails.add(key)
                lst.append(key)
                if stats is not None:
                    stats["last_valid_email"] = key
                break
            needs_retry = count_api_errors and _wave_seller_needs_api_retry(
                results,
                priority_emails,
                seller_already_found=bool(found_by_idx[seller_i]),
            )
            if needs_retry:
                if seller_api_fail[seller_i] == 0 and stats is not None:
                    stats["api_errors"] = int(stats.get("api_errors") or 0) + 1
                seller_api_fail[seller_i] = 1
            if len(found_by_idx[seller_i]) < per_seller_limit:
                for _e, ok, raw in results:
                    if not ok or _is_cancelled_raw(raw):
                        continue
                    key = (_e or "").strip().lower()
                    if not key or key in seen_valid_emails:
                        continue
                    if len(found_by_idx[seller_i]) >= per_seller_limit:
                        break
                    seen_valid_emails.add(key)
                    found_by_idx[seller_i].append(key)
                    if stats is not None:
                        stats["last_valid_email"] = key
                        logger.info("validemail hit seller=%s email=%s", seller_i, key)
                    combos_valid += 1
                    break
            return combos_valid

    async def _probe_one_list(
        seller_i: int,
        api_key: str,
        pending: list[str],
        *,
        count_api_errors: bool = True,
    ) -> str:
        if found_by_idx[seller_i] or not pending:
            return "hit" if found_by_idx[seller_i] else "no"
        max_attempts = _probe_max_attempts()
        last_verdict = "no"
        any_unknown = False
        for em in pending:
            if found_by_idx[seller_i]:
                return "hit"
            one = [em]
            results: list[tuple[str, bool, dict]] = []
            for attempt in range(max_attempts):
                dom_hint = (em.split("@")[-1] if em else "") or ""
                results = await _run_batch(
                    one,
                    seller_i=seller_i,
                    dom=dom_hint,
                    api_key=api_key,
                    stop_on_first_ok=False,
                )
                is_last = attempt >= max_attempts - 1
                cv = await _consume_wave_priority(
                    seller_i,
                    results,
                    one,
                    count_api_errors=count_api_errors and is_last,
                )
                async with state_lock:
                    if stats is not None:
                        stats["combinations_valid"] = int(
                            stats.get("combinations_valid") or 0
                        ) + cv
                    _refresh_stats()
                if found_by_idx[seller_i]:
                    return "hit"
                raw0 = results[0][2] if results else {}
                ok0 = bool(results[0][1]) if results else False
                if is_last or not _should_retry_same_domain(ok0, raw0):
                    break
                await asyncio.sleep(
                    _retry_delay_sec(attempt, raw0 if isinstance(raw0, dict) else {})
                )
            verdict = _domain_wave_verdict(results, one)
            if verdict == "hit":
                return "hit"
            if verdict == "unknown":
                any_unknown = True
                last_verdict = "unknown"
            elif last_verdict != "unknown":
                last_verdict = verdict
        if found_by_idx[seller_i]:
            return "hit"
        return "unknown" if any_unknown else last_verdict

    def _groups_by_domain(pending: list[str]) -> list[list[str]]:
        by_dom: dict[str, list[str]] = {}
        for em in pending:
            dom = (em or "").split("@")[-1].lower()
            by_dom.setdefault(dom, []).append(em)
        out: list[list[str]] = []
        for dom in domains_clean:
            grp = by_dom.get(dom.lower())
            if grp:
                out.append(grp)
        return out or [pending]

    async def _probe_batch(
        seller_i: int,
        api_key: str,
        priority_emails: list[str],
        *,
        count_api_errors: bool = True,
    ) -> None:
        """Параллельный запрос; при 429 повторяем только упавшие адреса."""
        pending = [e for e in priority_emails if (e or "").strip()]
        if found_by_idx[seller_i] or not pending:
            return
        if probe_by_domain_waves() and len(domains_clean) > 1:
            groups = _groups_by_domain(pending)
            for gi, grp in enumerate(groups):
                if found_by_idx[seller_i]:
                    return
                await _probe_one_list(
                    seller_i,
                    api_key,
                    grp,
                    count_api_errors=True,
                )
            return
        await _probe_one_list(
            seller_i,
            api_key,
            pending,
            count_api_errors=count_api_errors,
        )

    async def _validate_seller(
        i: int,
        api_key: str,
        *,
        tier_probe: bool = True,
        count_api_errors: bool = True,
    ) -> None:
        row = prepared[i]
        async with state_lock:
            if stats is not None:
                stats["current_seller_name"] = str(row.get("person_name") or "")[:60]

        raw_item = row.get("raw")
        if isinstance(raw_item, dict):
            embedded = _extract_emails_from_offer(raw_item)
            if embedded:
                await _probe_batch(
                    i,
                    api_key,
                    [e.lower() for e in embedded],
                    count_api_errors=count_api_errors,
                )
                if found_by_idx[i]:
                    nk = str(prepared[i].get("name_key") or "").strip()
                    if nk:
                        async with state_lock:
                            pending_seller_names.add(nk)
                            batch_seen_names.add(nk)
                    return

        locals_list = list(row.get("locals") or [])[: max_locals_per_seller()]
        if not tier_probe:
            locals_list = list(row.get("locals") or [])[: max(2, max_locals_per_seller())]
        if not locals_list:
            return

        # Нашли — стоп. Нет ящика — следующий домен. Несколько unknown подряд — не ждём 12 минут.
        unknown_streak = 0
        unknown_cap = max_unknown_domains_per_seller()
        for dom, wave in _domain_priority_waves(locals_list, domains_clean):
            if found_by_idx[i]:
                break
            if stats is not None:
                async with state_lock:
                    stats["current_domain"] = dom
            verdict = await _probe_one_list(
                i,
                api_key,
                wave,
                count_api_errors=count_api_errors,
            )
            if found_by_idx[i] or verdict == "hit":
                break
            if verdict == "no":
                unknown_streak = 0
                continue
            unknown_streak += 1
            if unknown_streak >= unknown_cap:
                break

        nk = str(prepared[i].get("name_key") or "").strip()
        if found_by_idx[i] and nk:
            async with state_lock:
                pending_seller_names.add(nk)
                batch_seen_names.add(nk)

    n_sellers = len(prepared)
    if stats is not None:
        stats["sellers_total"] = n_sellers

    seller_sem_cap = max(1, sellers_parallel * n_keys)
    if stats is not None:
        stats["seller_parallel_cap"] = seller_sem_cap

    async def _run_sellers_batched() -> None:
        """Все продавцы в одной очереди (sem), без синхронных «волн» по 120 шт."""
        nonlocal sellers_completed
        timeout = seller_validation_timeout_sec()
        sem = asyncio.Semaphore(seller_sem_cap)

        async def _run_one_seller(i: int) -> None:
            nonlocal sellers_completed
            my_key = api_keys[i % n_keys]
            try:
                await asyncio.wait_for(_validate_seller(i, my_key), timeout=timeout)
            except asyncio.TimeoutError:
                logger.warning("validemail seller timeout idx=%s name=%s", i, prepared[i].get("person_name"))
                if seller_api_fail[i] == 0 and stats is not None:
                    stats["api_errors"] = int(stats.get("api_errors") or 0) + 1
                seller_api_fail[i] = 1
                if stats is not None:
                    stats["seller_timeouts"] = int(stats.get("seller_timeouts") or 0) + 1
            async with state_lock:
                sellers_completed += 1
                if stats is not None:
                    stats["seller_index"] = sellers_completed
                    stats["sellers_total"] = len(prepared)
                    _refresh_stats()

        async def _limited(i: int) -> None:
            async with sem:
                await _run_one_seller(i)

        await asyncio.gather(*(_limited(i) for i in range(n_sellers)))

    await _run_sellers_batched()

    if stats is not None:
        stats["sellers_api_unresolved"] = sum(
            1
            for i in range(n_sellers)
            if not found_by_idx[i] and seller_api_fail[i] > 0
        )
        stats["api_error_sellers"] = int(stats.get("api_errors") or 0)
        stats["phase"] = ""

    found_count = sum(1 for f in found_by_idx if f)
    if stats is not None:
        logger.info(
            "validemail done: sellers=%s found=%s checked=%s api_errors=%s",
            len(prepared),
            found_count,
            int(stats.get("emails_checked") or 0),
            int(stats.get("api_errors") or 0),
        )
        if found_count == 0 and len(prepared) >= 30:
            logger.warning(
                "validemail ZERO yield: sellers=%s timeout=%s pool=%s per_key=%s probe_domains=%s",
                len(prepared),
                stats.get("validemail_api_timeout"),
                stats.get("validemail_pool"),
                stats.get("validemail_per_key"),
                stats.get("domains_count"),
            )

    # 3) результат: одна проверка API на продавца, email — на каждый его лот в VOID
    from services.offer_storage import link_key

    seller_emails: dict[str, list[str]] = {}
    for i, row in enumerate(prepared):
        found = found_by_idx[i][:per_seller_limit]
        if not found:
            continue
        nk = str(row.get("name_key") or "").strip()
        if nk:
            seller_emails[nk] = found

    out_rows: list[dict[str, Any]] = []
    seen_link_keys: set[str] = set()
    for it in items:
        if not isinstance(it, dict):
            continue
        raw_name = seller_name_from_item(it)
        nk = seller_name_key(raw_name) if (raw_name or "").strip() else ""
        found = seller_emails.get(nk) if nk else None
        if not found:
            continue
        lk = link_key(str(it.get("item_link") or it.get("link") or it.get("url") or ""))
        if lk:
            if lk in seen_link_keys:
                continue
            seen_link_keys.add(lk)
        out_rows.append({
            "raw": it,
            "person_name": _normalize_name(raw_name),
            "title": str(it.get("item_title") or it.get("title") or "").strip(),
            "price": str(it.get("item_price") or it.get("price") or "").strip(),
            "link": str(it.get("item_link") or it.get("link") or it.get("url") or "").strip(),
            "photo": str(
                it.get("item_photo") or it.get("photo") or it.get("image") or it.get("img") or ""
            ).strip(),
            "emails": list(found),
        })

    return out_rows



# -------------------------
# NEW API (services/validator.py)
# -------------------------

async def _validate_offers_new(
    *,
    telegram_id: int,
    offers: list[dict[str, Any]],
    bot: Bot,
    chat_id: int,
    config: ValidationConfig | None = None,
) -> dict[str, Any]:
    t0 = time.time()
    cfg = config or ValidationConfig()

    all_emails: list[str] = []
    offer_emails: list[list[str]] = []
    for off in offers:
        ems = _extract_emails_from_offer(off)
        offer_emails.append(ems)
        all_emails.extend(ems)

    seen = set()
    uniq_emails: list[str] = []
    for e in all_emails:
        el = e.strip().lower()
        if el and el not in seen:
            seen.add(el)
            uniq_emails.append(e.strip())

    from services.validemail_keys import resolve_validemail_api_keys

    api_keys = [str(k).strip() for k in (cfg.validemail_api_keys or []) if str(k).strip()]
    if not api_keys:
        single = (cfg.validemail_api_key or "").strip()
        if single:
            api_keys = [single]
    if not api_keys:
        api_keys = resolve_validemail_api_keys()

    if not api_keys:
        return {
            "summary_text": (
                f"{html_emoji('fail')} Не найден validemail API key. "
                "Задай VALIDEMAIL_API_KEYS в config."
            ),
            "output_json_bytes": None,
            "output_filename": None,
            "stats": {"total_offers": len(offers), "total_emails": len(uniq_emails), "error": "no_api_key"},
        }

    total = len(uniq_emails)
    progress_msg = await bot.send_message(
        chat_id=chat_id,
        text=(
            f"{html_emoji('search')} Валидация началась…\n"
            f"Email'ов: <b>{total}</b>"
        ),
        parse_mode="HTML",
    )

    from services.validemail_keys import validation_pool_size

    n_k = max(1, len(api_keys))
    results = await validate_emails_fast(
        uniq_emails,
        api_keys=api_keys,
        concurrency=validation_pool_size(n_k),
        url=str(cfg.validation_url or DEFAULT_VALIDEMAIL_URL).strip(),
        use_ssl_verify=bool(cfg.use_ssl_verify),
        progress_cb=None,
    )

    by_email: dict[str, tuple[bool, dict]] = {}
    for e, ok, raw in results:
        by_email[(e or "").strip().lower()] = (bool(ok), raw if isinstance(raw, dict) else {"raw": str(raw)})

    valid_count = 0
    invalid_count = 0
    offers_out: list[dict[str, Any]] = []

    for off, ems in zip(offers, offer_emails):
        off2 = dict(off)
        checks: list[dict[str, Any]] = []
        any_valid = False

        for e in ems:
            key = e.strip().lower()
            ok, raw = by_email.get(key, (False, {"error": "not_checked"}))
            checks.append({"email": e, "ok": ok, "raw": raw})
            if ok:
                any_valid = True

        off2["validemail_checked"] = True
        off2["validemail_any_ok"] = any_valid
        off2["validemail_results"] = checks

        if ems:
            if any_valid:
                valid_count += 1
            else:
                invalid_count += 1

        offers_out.append(off2)

    elapsed = max(0.01, time.time() - t0)

    try:
        await progress_msg.edit_text(
            f"{html_emoji('ok')} Валидация завершена.\n"
            f"{html_emoji('presets')} Офферов: <b>{len(offers)}</b>\n"
            f"{html_emoji('email')} Уникальных email: <b>{total}</b>\n"
            f"{html_emoji('green')} Офферов с валидным email: <b>{valid_count}</b>\n"
            f"{html_emoji('fail')} Офферов без валидного email: <b>{invalid_count}</b>\n"
            f"{html_emoji('wait')} Время: <b>{elapsed:.1f}s</b>",
            parse_mode="HTML",
        )
    except Exception:
        pass

    out_bytes = json.dumps(offers_out, ensure_ascii=False, indent=2).encode("utf-8")
    out_name = f"validated_{telegram_id}.json"

    return {
        "summary_text": (
            f"{html_emoji('ok')} Валидация завершена.\n"
            f"Офферов: {len(offers)} | Уникальных email: {total} | "
            f"OK-офферов: {valid_count} | BAD-офферов: {invalid_count} | "
            f"{elapsed:.1f}s"
        ),
        "output_json_bytes": out_bytes,
        "output_filename": out_name,
        "stats": {
            "total_offers": len(offers),
            "unique_emails": total,
            "offers_any_ok": valid_count,
            "offers_all_bad": invalid_count,
            "seconds": elapsed,
        },
    }


# -------------------------
# Public wrapper (оба интерфейса)
# -------------------------

async def validate_offers(*args, **kwargs):
    """
    OLD: validate_offers(items, domains, cfg, progress_cb=...)
    NEW: validate_offers(telegram_id=..., offers=..., bot=..., chat_id=..., config=...)
    """
    if "telegram_id" in kwargs or "offers" in kwargs:
        return await _validate_offers_new(
            telegram_id=int(kwargs["telegram_id"]),
            offers=list(kwargs["offers"]),
            bot=kwargs["bot"],
            chat_id=int(kwargs["chat_id"]),
            config=kwargs.get("config"),
        )

    if len(args) >= 3 and isinstance(args[0], list) and isinstance(args[1], list):
        items = args[0]
        domains = args[1]
        cfg = args[2]
        progress_cb = kwargs.get("progress_cb")
        stats = kwargs.get("stats")
        return await _validate_offers_old(
            items, domains, cfg, progress_cb=progress_cb, stats=stats
        )

    raise TypeError("validate_offers(): unsupported call signature")
