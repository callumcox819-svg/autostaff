"""SMTP sending that always runs through the user's proxy."""
from __future__ import annotations

import logging
import os
import random
import time
from typing import List, Optional, Tuple

from sqlalchemy import or_ as sa_or
from sqlalchemy import select as sa_select
from sqlalchemy.ext.asyncio import AsyncSession

from models import EmailAccount, Proxy
from proxy_manager import ProxySMTPContext, is_mailing_proxy
from services.sender import (
    is_definite_proxy_failure,
    is_smtp_timeout_error,
    normalize_send_error,
    send_batch_via_account,
    send_email_via_account,
    send_email_via_isolated_proxy,
    should_retry_send_with_other_proxy,
)
from services.proxy_manager import ProxyManager

logger = logging.getLogger(__name__)

NO_ACTIVE_PROXY = "PROXY_ERROR|no_active_proxy|No active proxy configured"

# Ответ продавцу: Loma/residential — login+STARTTLS+DATA, не 45 с.
REPLY_SMTP_TIMEOUT_SEC = max(30, min(120, int(os.getenv("REPLY_SMTP_TIMEOUT_SEC", "75"))))
REPLY_SMTP_MAX_PROXIES = max(1, min(6, int(os.getenv("REPLY_SMTP_MAX_PROXIES", "3"))))
REPLY_SMTP_PROXY_RETRIES = max(1, min(4, int(os.getenv("REPLY_SMTP_PROXY_RETRIES", "3"))))

# Рассылка /send: несколько SOCKS5, таймаут на каждую попытку.
MAIL_SMTP_TIMEOUT_SEC = max(20, min(90, int(os.getenv("MAIL_SMTP_TIMEOUT_SEC", "45"))))
# Фаст + один ротирующий gateway (Loma: login+DATA дольше — не 18 с).
MAIL_FAST_SMTP_TIMEOUT_SEC = max(
    8, min(120, int(os.getenv("MAIL_FAST_SMTP_TIMEOUT_SEC", "15")))
)
# Sticky/ротирующий прокси: при EOF/timeout — новое соединение (новый IP), не сразу fail.
MAIL_STICKY_PROXY_RECONNECTS = max(
    1, min(5, int(os.getenv("MAIL_STICKY_PROXY_RECONNECTS", "3")))
)
MAIL_STICKY_PROXY_RECONNECT_PAUSE_SEC = max(
    0.0, min(3.0, float(os.getenv("MAIL_STICKY_PROXY_RECONNECT_PAUSE_SEC", "0.35")))
)
MAIL_SMTP_MAX_PROXIES = max(1, min(12, int(os.getenv("MAIL_SMTP_MAX_PROXIES", "10"))))
# Явный id ротирующего SOCKS5 в БД (опционально; иначе первый 🟢).
_ROTATING_PROXY_ID_RAW = (os.getenv("ROTATING_PROXY_ID") or "").strip()
ROTATING_PROXY_ID: int | None = (
    int(_ROTATING_PROXY_ID_RAW) if _ROTATING_PROXY_ID_RAW.isdigit() else None
)

_LAST_OK_PROXY_ID: dict[int, int] = {}
# Пара (user_id, account_id) → proxy_id — один ящик стабильнее через один egress (инбокс).
_LAST_OK_PROXY_BY_ACCOUNT: dict[tuple[int, int], int] = {}


async def choose_required_proxy(
    session: AsyncSession,
    user_id: int,
    *,
    exclude_ids: set[int] | None = None,
) -> Tuple[Optional[Proxy], Optional[str]]:
    """
    (proxy, None) — ок.
    (None, NO_ACTIVE_PROXY) — в БД нет ни одного активного прокси (SOCKS/HTTP).
    (None, None) — все доступные прокси уже пробовали в этом send (не «мёртвые»).
    """
    from proxy_manager import choose_proxy_for_user

    proxy = await choose_proxy_for_user(session, int(user_id), exclude_ids=exclude_ids)
    if proxy:
        return proxy, None
    if exclude_ids:
        return None, None
    return None, NO_ACTIVE_PROXY


def _smtp_eligible_proxy_row(p: Proxy) -> bool:
    return is_mailing_proxy(p)


async def _list_active_mailing_proxies(session: AsyncSession, user_id: int) -> List[Proxy]:
    """SOCKS/HTTP для рассылки: без 🔴 (is_active=False). 🟢 и 🟡 (None) — можно."""
    rows = (
        await session.execute(
            sa_select(Proxy)
            .where(Proxy.user_id == int(user_id))
            .order_by(Proxy.id)
        )
    ).scalars().all()
    out: List[Proxy] = []
    for p in rows:
        if not _smtp_eligible_proxy_row(p):
            continue
        if p.is_active is False:
            continue
        out.append(p)

    def _pref_key(px: Proxy) -> int:
        if px.is_active is True:
            return 0
        return 1

    out.sort(key=_pref_key)
    return out


def _proxy_try_limit(*, fast: bool, proxy_count: int) -> int:
    if proxy_count <= 0:
        return 0
    if fast:
        return min(proxy_count, REPLY_SMTP_MAX_PROXIES)
    return min(proxy_count, MAIL_SMTP_MAX_PROXIES)


async def user_has_active_mailing_proxy(session: AsyncSession, user_id: int) -> bool:
    """Есть ли хотя бы один SOCKS5/HTTP прокси для SMTP (🟢 или 🟡)."""
    return bool(await _list_active_mailing_proxies(session, int(user_id)))


NO_MAILING_PROXY = (
    "PROXY_ERROR|no_active_proxy|"
    "Нет прокси. Добавь SOCKS5 или HTTP в «Настройки → Прокси»."
)


async def pick_sticky_proxy_for_fast_mailing(
    session: AsyncSession,
    user_id: int,
) -> Optional[Proxy]:
    """Один 🟢 SOCKS5 (ротирующий gateway) на всю фаст-сессию."""
    proxies = await _list_active_mailing_proxies(session, user_id)
    if not proxies:
        return None
    if ROTATING_PROXY_ID is not None:
        pinned = [p for p in proxies if int(p.id) == int(ROTATING_PROXY_ID)]
        if pinned:
            return pinned[0]
    green = [p for p in proxies if p.is_active is True]
    if green:
        return green[0]
    return proxies[0]


def _order_proxies_for_send(
    user_id: int,
    proxies: List[Proxy],
    *,
    fast: bool,
    account_id: int | None = None,
    sticky_proxy_id: int | None = None,
) -> List[Proxy]:
    if not proxies:
        return []
    if sticky_proxy_id is not None:
        pinned = [p for p in proxies if int(p.id) == int(sticky_proxy_id)]
        return pinned[:1]
    uid = int(user_id)
    sticky_id = None
    if account_id is not None:
        sticky_id = _LAST_OK_PROXY_BY_ACCOUNT.get((uid, int(account_id)))
    last_id = sticky_id or _LAST_OK_PROXY_ID.get(uid)
    head: List[Proxy] = []
    mid: List[Proxy] = []
    tail: List[Proxy] = []
    for p in proxies:
        pid = int(p.id)
        if last_id and pid == int(last_id):
            head.append(p)
        elif sticky_id and pid == int(sticky_id) and p not in head:
            mid.append(p)
        else:
            tail.append(p)
    random.shuffle(tail)
    order = head + mid + tail
    limit = _proxy_try_limit(fast=fast, proxy_count=len(order))
    return order[:limit]


def _proxy_deactivate_on_fail(*, mailing_fast: bool, err: str | None) -> bool:
    """В фаст-режиме не ставим 🔴 на прокси — только last_error (ложные disconnect)."""
    if mailing_fast:
        return False
    return is_definite_proxy_failure(err)


async def send_email_via_account_with_proxy(
    session: AsyncSession,
    user_id: int,
    account: EmailAccount,
    to_email: str,
    subject: str,
    body: str,
    sender_name: Optional[str] = None,
    is_html: Optional[bool] = None,
    *,
    fast: bool = False,
    sticky_proxy_id: int | None = None,
    mailing_fast: bool = False,
    in_reply_to: Optional[str] = None,
    references: Optional[str] = None,
) -> Tuple[bool, Optional[str], Optional[str]]:
    proxies = await _list_active_mailing_proxies(session, user_id)
    if not proxies:
        return False, NO_MAILING_PROXY, None

    if sticky_proxy_id is not None:
        proxies = [p for p in proxies if int(p.id) == int(sticky_proxy_id)]
        if not proxies:
            return False, NO_MAILING_PROXY, None

    order = _order_proxies_for_send(
        int(user_id),
        proxies,
        fast=fast,
        account_id=int(account.id),
        sticky_proxy_id=sticky_proxy_id,
    )
    # fast=True — только быстрые ответы в чате; рассылка всегда с MAIL_SMTP_TIMEOUT_SEC
    smtp_tmo = REPLY_SMTP_TIMEOUT_SEC if fast else MAIL_SMTP_TIMEOUT_SEC
    if order:
        from services.residential_proxy import is_residential_gateway, residential_smtp_timeout_sec

        if is_residential_gateway(order[0]):
            base_fast = min(
                int(smtp_tmo), int(os.getenv("BURST_FAST_SMTP_TIMEOUT_CAP_SEC", "20"))
            )
            boosted = int(residential_smtp_timeout_sec())
            smtp_tmo = min(max(base_fast, boosted), base_fast * 2)

    last_err: str | None = None
    last_msgid: str | None = None
    tried = 0

    for proxy in order:
        pid = int(proxy.id)
        attempts = REPLY_SMTP_PROXY_RETRIES if fast else 1
        for attempt in range(1, attempts + 1):
            tried += 1
            logger.info(
                "[SMTP send] try proxy_id=%s %s:%s account=%s -> %s (%s/%s fast=%s sticky=%s attempt=%s tmo=%ss)",
                pid,
                proxy.host,
                proxy.port,
                account.email,
                to_email,
                tried,
                len(order) * attempts,
                fast,
                sticky_proxy_id,
                attempt,
                smtp_tmo,
            )
            if fast:
                ok, err, msgid = await send_email_via_isolated_proxy(
                    proxy,
                    account,
                    to_email,
                    subject,
                    body,
                    sender_name=sender_name,
                    is_html=is_html,
                    smtp_timeout_sec=smtp_tmo,
                    in_reply_to=in_reply_to,
                    references=references,
                )
            else:
                async with ProxySMTPContext(proxy):
                    ok, err, msgid = await send_email_via_account(
                        account,
                        to_email,
                        subject,
                        body,
                        sender_name=sender_name,
                        is_html=is_html,
                        smtp_timeout_sec=smtp_tmo,
                        in_reply_to=in_reply_to,
                        references=references,
                    )
            err = normalize_send_error(err)
            if ok:
                _LAST_OK_PROXY_ID[int(user_id)] = pid
                _LAST_OK_PROXY_BY_ACCOUNT[(int(user_id), int(account.id))] = pid
                try:
                    await ProxyManager.note_proxy_success(session, pid)
                except Exception:
                    pass
                return True, err, msgid

            last_err = err
            last_msgid = msgid
            logger.warning(
                "[SMTP send] fail proxy_id=%s account=%s err=%s attempt=%s",
                pid,
                account.email,
                (err or "")[:200],
                attempt,
            )
            if not should_retry_send_with_other_proxy(err):
                break
            if attempt < attempts:
                time.sleep(1.2)
                continue
            break

        dead = _proxy_deactivate_on_fail(mailing_fast=mailing_fast, err=last_err)
        try:
            await ProxyManager.note_proxy_failure(
                session,
                pid,
                (last_err or "")[:500],
                deactivate=dead,
                from_mailing=True,
            )
        except Exception:
            pass

        if not should_retry_send_with_other_proxy(last_err):
            return False, last_err, last_msgid

    hint = (
        f"Ни один из {tried} прокси не достучался до Gmail SMTP "
        f"(последняя: {last_err or 'timeout'}). "
        f"«Прокси» → проверить — нужно SMTP+STARTTLS OK."
    )
    if is_smtp_timeout_error(last_err):
        return False, f"SMTP_TIMEOUT|all_proxies|{hint}", last_msgid
    return False, last_err or NO_ACTIVE_PROXY, last_msgid


async def send_email_via_account_with_proxy_isolated(
    session: AsyncSession,
    user_id: int,
    account: EmailAccount,
    to_email: str,
    subject: str,
    body: str,
    sender_name: Optional[str] = None,
    is_html: Optional[bool] = None,
    *,
    mailing_fast: bool = True,
    sticky_proxy_id: int | None = None,
) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Параллельный фаст: каждый ящик — свой SOCKS5/HTTP-сокет, без глобального _PROXY_LOCK.
    Ротирующий gateway: sticky_proxy_id = один прокси на всю /send.
    """
    proxies = await _list_active_mailing_proxies(session, user_id)
    if not proxies:
        return False, NO_MAILING_PROXY, None

    if sticky_proxy_id is not None:
        order = _order_proxies_for_send(
            int(user_id),
            proxies,
            fast=False,
            sticky_proxy_id=int(sticky_proxy_id),
        )
        if not order:
            return False, NO_MAILING_PROXY, None
    else:
        order = _order_proxies_for_send(
            int(user_id), proxies, fast=False, account_id=int(account.id)
        )
    smtp_tmo = (
        MAIL_FAST_SMTP_TIMEOUT_SEC
        if mailing_fast
        else MAIL_SMTP_TIMEOUT_SEC
    )
    if mailing_fast and sticky_proxy_id is not None and len(order) <= 1:
        smtp_tmo = max(
            int(smtp_tmo),
            min(35, int(os.getenv("BURST_SINGLE_PROXY_SMTP_TIMEOUT_SEC", "25"))),
        )
    if mailing_fast and order:
        from services.residential_proxy import is_residential_gateway, residential_smtp_timeout_sec

        if is_residential_gateway(order[0]):
            base_fast = int(smtp_tmo)
            boosted = int(residential_smtp_timeout_sec())
            smtp_tmo = min(40, max(base_fast, boosted))
    last_err: str | None = None
    last_msgid: str | None = None
    tried = 0
    sticky_reconnects = (
        MAIL_STICKY_PROXY_RECONNECTS
        if sticky_proxy_id is not None
        else 1
    )

    for proxy in order:
        pid = int(proxy.id)
        for reconnect in range(1, sticky_reconnects + 1):
            tried += 1
            logger.info(
                "[SMTP isolated] try proxy_id=%s %s:%s account=%s -> %s "
                "(%s/%s tmo=%ss reconnect=%s/%s)",
                pid,
                proxy.host,
                proxy.port,
                account.email,
                to_email,
                tried,
                max(len(order), 1) * sticky_reconnects,
                smtp_tmo,
                reconnect,
                sticky_reconnects,
            )
            ok, err, msgid = await send_email_via_isolated_proxy(
                proxy,
                account,
                to_email,
                subject,
                body,
                sender_name=sender_name,
                is_html=is_html,
                smtp_timeout_sec=smtp_tmo,
                for_mailing=True,
            )
            err = normalize_send_error(err)
            if ok:
                _LAST_OK_PROXY_ID[int(user_id)] = pid
                _LAST_OK_PROXY_BY_ACCOUNT[(int(user_id), int(account.id))] = pid
                try:
                    await ProxyManager.note_proxy_success(session, pid)
                except Exception:
                    pass
                return True, err, msgid

            last_err = err
            last_msgid = msgid
            logger.warning(
                "[SMTP isolated] fail proxy_id=%s account=%s reconnect=%s/%s err=%s",
                pid,
                account.email,
                reconnect,
                sticky_reconnects,
                (err or "")[:200],
            )

            dead = _proxy_deactivate_on_fail(mailing_fast=mailing_fast, err=err)
            try:
                await ProxyManager.note_proxy_failure(
                    session,
                    pid,
                    (err or "")[:500],
                    deactivate=dead,
                    from_mailing=True,
                )
            except Exception:
                pass

            if not should_retry_send_with_other_proxy(err):
                return False, err, last_msgid

            # EOF/timeout на ротаторе — пауза и новое TCP (часто новый IP).
            if reconnect < sticky_reconnects:
                if MAIL_STICKY_PROXY_RECONNECT_PAUSE_SEC > 0:
                    import asyncio

                    await asyncio.sleep(MAIL_STICKY_PROXY_RECONNECT_PAUSE_SEC)
                continue
            break

        # Sticky: только этот gateway; без sticky — следующий прокси из списка.
        if mailing_fast and sticky_proxy_id is not None:
            break
        if not should_retry_send_with_other_proxy(last_err):
            break

    if sticky_proxy_id is not None:
        hint = (
            f"Прокси proxy_id={sticky_proxy_id} — нет ответа от Gmail SMTP "
            f"после {tried} попыток ({last_err or 'timeout'}). "
            f"Повтор даёт новый IP (ротация)."
        )
    else:
        hint = (
            f"Ни один из {tried} прокси не достучался до Gmail SMTP "
            f"(последняя: {last_err or 'timeout'})."
        )
    if is_smtp_timeout_error(last_err):
        return False, f"SMTP_TIMEOUT|all_proxies|{hint}", last_msgid
    return False, last_err or NO_ACTIVE_PROXY, last_msgid


async def send_batch_via_account_with_proxy(
    session: AsyncSession,
    user_id: int,
    account: EmailAccount,
    items: list[tuple[str, str, str]],
    sender_name: Optional[str] = None,
    *,
    fast: bool = False,
    mailing_fast: bool = False,
) -> List[Tuple[bool, Optional[str]]]:
    """Отправка пачки: неудачные адреса повторяются на следующем SOCKS5 (не «3 из 10»)."""
    n = len(items)
    if n == 0:
        return []

    proxies = await _list_active_mailing_proxies(session, user_id)
    if not proxies:
        return [(False, NO_ACTIVE_PROXY) for _ in items]

    order = _order_proxies_for_send(
        int(user_id), proxies, fast=fast, account_id=int(account.id)
    )
    merged: List[Tuple[bool, Optional[str]]] = [(False, NO_ACTIVE_PROXY) for _ in range(n)]
    pending: List[int] = list(range(n))

    for proxy in order:
        if not pending:
            break

        pid = int(proxy.id)
        batch_items = [items[i] for i in pending]
        logger.info(
            "[SMTP batch] proxy_id=%s account=%s pending=%s/%s",
            pid,
            account.email,
            len(batch_items),
            n,
        )

        async with ProxySMTPContext(proxy):
            raw = await send_batch_via_account(
                account,
                batch_items,
                sender_name=sender_name,
                smtp_timeout_sec=MAIL_SMTP_TIMEOUT_SEC,
            )

        new_pending: List[int] = []
        any_ok = False
        for j, idx in enumerate(pending):
            ok, err = raw[j] if j < len(raw) else (False, "BATCH_INDEX_ERROR")
            err_n = normalize_send_error(err)
            merged[idx] = (bool(ok), err_n)
            if ok:
                any_ok = True
            elif should_retry_send_with_other_proxy(err_n):
                new_pending.append(idx)

        if any_ok:
            _LAST_OK_PROXY_ID[int(user_id)] = pid
            _LAST_OK_PROXY_BY_ACCOUNT[(int(user_id), int(account.id))] = pid
            try:
                await ProxyManager.note_proxy_success(session, pid)
            except Exception:
                pass

        if not new_pending:
            return merged

        last_err = next((e for o, e in merged if not o and e), None)
        dead = _proxy_deactivate_on_fail(mailing_fast=mailing_fast, err=last_err)
        try:
            await ProxyManager.note_proxy_failure(
                session,
                pid,
                (last_err or "batch fail")[:500],
                deactivate=dead,
                from_mailing=True,
            )
        except Exception:
            pass

        if not should_retry_send_with_other_proxy(last_err):
            return merged

        pending = new_pending

    return merged
