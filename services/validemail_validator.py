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
from utils.ui_emoji import html_emoji
from services.seller_name import (
    MIN_NAME_TOKEN_LEN,
    MIN_SELLER_LETTERS,
    normalize_seller_name,
    pick_handle_locals,
    pick_name_tokens,
    pick_name_tokens_for_email,
    seller_name_eligible_for_validation,
    seller_name_from_item,
    seller_name_too_short,
)

logger = logging.getLogger(__name__)

# Только пользовательский blacklist из настроек (не режем имена из JSON автоматически).
DEFAULT_VALIDEMAIL_URL = "https://validemail.co/api/v1/validate"


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


# -------------------------
# Helpers: name normalization
# -------------------------

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
    Логины из имени продавца: Maria Johansen → maria.johansen; Martuis2 → martuis2.
    Приоритет: ник (Semiuel2421) или first.last (Sam Day → sam.day), затем firstlast.
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
        seen.add(local)
        out.append(local)

    handles = pick_handle_locals(name)
    if handles and len(parts) <= 1:
        for h in handles:
            _add(h)
        return out

    tokens = _pick_alpha_tokens(name)
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
    _add(f"{first}.{last}")
    _add(f"{first}{last}")
    if len(first) >= 2 and len(last) >= 2:
        _add(f"{first[0]}{last}")
        _add(f"{first[0]}.{last}")
    _add(f"{first}_{last}")
    if len(last) >= 3:
        _add(f"{last}.{first}")
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


def _is_api_failure(_ok: bool, raw: object) -> bool:
    """Сбой API/сети. Ответ «ящик не существует» (HTTP 200 / undeliverable) — не ошибка."""
    if _ok:
        return False
    if not isinstance(raw, dict):
        return True
    try:
        st = int(raw.get("_http_status") or 0)
    except (TypeError, ValueError):
        st = 0
    if st == 200:
        return False

    reason = str(raw.get("reason") or raw.get("Reason") or "").lower().strip()
    if reason in ("connection_error", "timeout"):
        return True
    if reason in _DEFINITIVE_BAD_REASONS:
        return False

    status = str(raw.get("status") or raw.get("State") or raw.get("state") or "").lower().strip()
    if status in (
        "deliverable",
        "undeliverable",
        "unknown",
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


def _should_retry_same_domain(ok: bool, raw: object) -> bool:
    """429/сеть — повторяем тот же домен, не переходим к следующему."""
    if ok:
        return False
    if isinstance(raw, dict) and raw.get("_api_key_error"):
        return False
    if _is_api_failure(ok, raw):
        return True
    return _is_transient_failure(raw)


def _probe_max_attempts() -> int:
    try:
        return max(1, min(5, int(os.getenv("VALIDEMAIL_PROBE_RETRIES", "2"))))
    except (TypeError, ValueError):
        return 3


# -------------------------
# NEW API helpers (/validate)
# -------------------------

def _extract_emails_from_offer(offer: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for key in ("emails", "email", "seller_email", "from_email"):
        if key not in offer:
            continue
        v = offer.get(key)
        if isinstance(v, str):
            e = v.strip()
            if e:
                out.append(e)
        elif isinstance(v, list):
            for x in v:
                if isinstance(x, str):
                    e = x.strip()
                    if e:
                        out.append(e)
                elif isinstance(x, dict):
                    ev = x.get("email")
                    if isinstance(ev, str) and ev.strip():
                        out.append(ev.strip())

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
                "duplicates": 0,
                "api_errors": 0,
                "no_name": 0,
            }
        )

    from services.seller_blacklist import seller_name_key

    seller_bl = set(cfg.seller_name_keys or set())
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
        if name_key and name_key in seller_bl:
            if stats is not None:
                stats["blacklisted"] = int(stats.get("blacklisted") or 0) + 1
            continue

        if name_key and name_key in batch_seen_names:
            if stats is not None:
                stats["blacklisted"] = int(stats.get("blacklisted") or 0) + 1
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
        max_domains_per_seller,
        max_locals_per_seller,
        seller_batch_pause_sec,
        seller_batch_size,
        seller_parallel_per_key,
        seller_validation_timeout_sec,
        validation_concurrency_plan,
        validation_pool_size,
    )

    dom_cap = max_domains_per_seller()
    if dom_cap > 0:
        domains_clean = domains_clean[:dom_cap]

    n_keys = max(1, len(api_keys))
    per_key_limit, parallel_pool = validation_concurrency_plan(n_keys)
    sellers_parallel = seller_parallel_per_key()
    limit = max(2, int(cfg.concurrency) or validation_pool_size(n_keys))
    parallel_pool = max(parallel_pool, min(limit, per_key_limit * n_keys))

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
        stats["validemail_per_key"] = per_key_limit
        stats["validemail_threads"] = n_keys
        stats["validemail_pool"] = parallel_pool
        stats["domains_count"] = len(domains_clean)
        stats["max_locals"] = max_locals_per_seller()

    logger.info(
        "validemail: keys=%s × %s req/key pool=%s batch=%s pause=%.2fs sellers=%s domains=%s",
        n_keys,
        per_key_limit,
        parallel_pool,
        seller_batch_size(),
        seller_batch_pause_sec(),
        len(prepared),
        len(domains_clean),
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

        use_keys = api_keys if n_keys > 1 else [api_key]
        return await validate_emails_fast(
            batch_emails,
            api_keys=use_keys,
            concurrency=parallel_pool,
            url=url,
            use_ssl_verify=bool(cfg.use_ssl_verify),
            progress_cb=lambda d, t, l, u, _bd=base_done: _wrap_progress(d, t, l, u, _bd),
        )

    async def _consume_results(
        seller_i: int,
        results: list[tuple[str, bool, dict]],
        *,
        count_api_errors: bool = True,
    ) -> int:
        nonlocal overall_done
        async with state_lock:
            overall_done += len(results)
            combos_valid = 0
            for _e, ok, raw in results:
                if len(found_by_idx[seller_i]) >= per_seller_limit:
                    break
                if not ok:
                    if count_api_errors and stats is not None and _is_api_failure(ok, raw):
                        stats["api_errors"] = int(stats.get("api_errors") or 0) + 1
                        seller_api_fail[seller_i] += 1
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
            overall_done += len(results)
            combos_valid = 0
            wave_api_fail = False
            for em_lc in priority_emails:
                em_lc = (em_lc or "").strip().lower()
                row = by_lc.get(em_lc)
                if not row:
                    continue
                _e, ok, raw = row
                if len(found_by_idx[seller_i]) >= per_seller_limit:
                    break
                if not ok:
                    if _is_api_failure(ok, raw):
                        wave_api_fail = True
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
            if count_api_errors and wave_api_fail and stats is not None:
                stats["api_errors"] = int(stats.get("api_errors") or 0) + 1
                seller_api_fail[seller_i] += 1
            return combos_valid

    async def _probe_batch(
        seller_i: int,
        api_key: str,
        priority_emails: list[str],
    ) -> None:
        """Параллельный запрос; при 429 повторяем только упавшие адреса."""
        pending = [e for e in priority_emails if (e or "").strip()]
        if found_by_idx[seller_i] or not pending:
            return
        max_attempts = _probe_max_attempts()
        for attempt in range(max_attempts):
            dom_hint = (pending[0].split("@")[-1] if pending else "") or ""
            results = await _run_batch(
                pending,
                seller_i=seller_i,
                dom=dom_hint,
                api_key=api_key,
            )
            is_last = attempt >= max_attempts - 1
            cv = await _consume_wave_priority(
                seller_i,
                results,
                pending,
                count_api_errors=is_last,
            )
            async with state_lock:
                if stats is not None:
                    stats["combinations_valid"] = int(
                        stats.get("combinations_valid") or 0
                    ) + cv
                _refresh_stats()
            if found_by_idx[seller_i]:
                return
            by_lc = {(e or "").strip().lower(): (e, ok, raw) for e, ok, raw in results}
            retry_list: list[str] = []
            for em in pending:
                row = by_lc.get((em or "").strip().lower())
                if not row:
                    retry_list.append(em)
                    continue
                _e, ok, raw = row
                if _should_retry_same_domain(ok, raw):
                    retry_list.append(_e)
            if not retry_list or is_last:
                break
            pending = retry_list
            raw0 = results[0][2] if results else {}
            await asyncio.sleep(
                _retry_delay_sec(attempt, raw0 if isinstance(raw0, dict) else {})
            )

    async def _validate_seller(i: int, api_key: str) -> None:
        row = prepared[i]
        async with state_lock:
            if stats is not None:
                stats["current_seller_name"] = str(row.get("person_name") or "")[:60]

        locals_list = list(row.get("locals") or [])[: max_locals_per_seller()]
        if not locals_list:
            return

        priority_emails: list[str] = []
        seen_probe: set[str] = set()
        for loc in locals_list:
            loc = (loc or "").strip().lower()
            if not loc:
                continue
            for dom in domains_clean:
                em = f"{loc}@{dom}".lower()
                if em in seen_probe:
                    continue
                seen_probe.add(em)
                priority_emails.append(em)
        if priority_emails:
            await _probe_batch(i, api_key, priority_emails)

        nk = str(prepared[i].get("name_key") or "").strip()
        if found_by_idx[i] and nk:
            async with state_lock:
                pending_seller_names.add(nk)
                batch_seen_names.add(nk)

    n_sellers = len(prepared)
    if stats is not None:
        stats["sellers_total"] = n_sellers

    async def _run_sellers_batched() -> None:
        """Пачки продавцов (по умолчанию 20) + пауза — меньше 429 и зависаний на 99%."""
        nonlocal sellers_completed
        bs = seller_batch_size()
        pause = seller_batch_pause_sec()
        timeout = seller_validation_timeout_sec()
        cap = max(1, sellers_parallel * n_keys)
        if bs > 0:
            cap = max(cap, min(bs, cap * 2))
        sem = asyncio.Semaphore(cap)

        async def _run_one_seller(i: int) -> None:
            nonlocal sellers_completed
            my_key = api_keys[i % n_keys]
            try:
                await asyncio.wait_for(_validate_seller(i, my_key), timeout=timeout)
            except asyncio.TimeoutError:
                logger.warning("validemail seller timeout idx=%s name=%s", i, prepared[i].get("person_name"))
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

        for b0 in range(0, n_sellers, bs):
            chunk = list(range(b0, min(b0 + bs, n_sellers)))
            if stats is not None:
                stats["current_batch"] = f"{chunk[0] + 1}-{chunk[-1] + 1}/{n_sellers}"
            await asyncio.gather(*(_limited(i) for i in chunk))
            if b0 + bs < n_sellers and pause > 0:
                await asyncio.sleep(pause)

    await _run_sellers_batched()

    found_count = sum(1 for f in found_by_idx if f)
    if stats is not None:
        logger.info(
            "validemail done: sellers=%s found=%s checked=%s api_errors=%s",
            len(prepared),
            found_count,
            int(stats.get("emails_checked") or 0),
            int(stats.get("api_errors") or 0),
        )

    # 3) собираем результат
    out_rows: list[dict[str, Any]] = []
    for i, row in enumerate(prepared):
        found = found_by_idx[i][:per_seller_limit]
        if not found:
            continue
        out_rows.append({
            "raw": row["raw"],
            "person_name": _normalize_name(row["person_name"]),
            "title": row["title"],
            "price": row["price"],
            "link": row["link"],
            "photo": row["photo"],
            "emails": found,
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
