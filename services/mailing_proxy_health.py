"""Проверка прокси (SOCKS5 / HTTP) перед рассылкой и периодически во время /send."""

from __future__ import annotations
from utils.ui_emoji import html_emoji, menu_path, toast, msg_fail, msg_ok, msg_wait, msg_warn

import asyncio
import logging
import os
from dataclasses import dataclass
from typing import Optional, Tuple

from aiogram import Bot
from sqlalchemy import select

from database import db_session
from models import Proxy
from proxy_manager import is_mailing_proxy
from services.proxy_verify import refresh_proxies_status

logger = logging.getLogger(__name__)

MAIL_PROXY_RECHECK_SEC = max(60, min(600, int(os.getenv("MAIL_PROXY_RECHECK_SEC", "120"))))
MAIL_PROXY_PREFLIGHT_TIMEOUT = max(18, min(45, int(os.getenv("MAIL_PROXY_PREFLIGHT_TIMEOUT", "28"))))
MAIL_FAST_PREFLIGHT_TIMEOUT = max(
    18, min(55, int(os.getenv("MAIL_FAST_PREFLIGHT_TIMEOUT", "42")))
)
MAIL_FAST_PREFLIGHT_SKIP = (os.getenv("MAIL_FAST_PREFLIGHT_SKIP", "1") or "").strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)
# skip | tunnel | full — перед фаст-/send (по умолчанию skip: не ждать Gmail SMTP)
MAIL_FAST_PREFLIGHT = (os.getenv("MAIL_FAST_PREFLIGHT", "skip") or "skip").strip().lower()
MAIL_PROXY_PREFLIGHT_CONCURRENCY = max(
    1, min(4, int(os.getenv("MAIL_PROXY_PREFLIGHT_CONCURRENCY", "2")))
)


@dataclass(frozen=True)
class ProxyHealthSummary:
    total: int
    ok: int
    unknown: int
    bad: int

    def format_lines(self) -> str:
        return (
            f"Прокси: <b>{self.total}</b> · {html_emoji('green')} SMTP OK: <b>{self.ok}</b> · "
            f"{html_emoji('yellow')} неясно: <b>{self.unknown}</b> · {html_emoji('red')} мёртв при рассылке: <b>{self.bad}</b>"
        )


async def summarize_proxy_health(session, user_id: int) -> ProxyHealthSummary:
    rows = list(
        (await session.execute(select(Proxy).where(Proxy.user_id == int(user_id)))).scalars().all()
    )
    eligible = [p for p in rows if is_mailing_proxy(p)]
    ok = unk = bad = 0
    for p in eligible:
        if p.is_active is True:
            ok += 1
        elif p.is_active is False:
            bad += 1
        else:
            unk += 1
    return ProxyHealthSummary(len(eligible), ok, unk, bad)


async def run_proxy_health_check(session, user_id: int) -> ProxyHealthSummary:
    """Туннель + smtp.gmail.com:587 — как в меню «Прокси»."""
    await refresh_proxies_status(
        session,
        int(user_id),
        concurrency=MAIL_PROXY_PREFLIGHT_CONCURRENCY,
        timeout=MAIL_PROXY_PREFLIGHT_TIMEOUT,
    )
    return await summarize_proxy_health(session, user_id)


def mailing_may_start(summary: ProxyHealthSummary, *, fast: bool = False) -> Tuple[bool, str]:
    if summary.total <= 0:
        return False, "Нет прокси в «Прокси» (SOCKS5 или HTTP)."
    if fast:
        if summary.ok >= 1:
            return (
                True,
                summary.format_lines()
                + f"\n<i>{html_emoji('burst')} Фаст: один {html_emoji('green')} прокси на всю рассылку.</i>",
            )
        if summary.unknown >= 1:
            return (
                True,
                summary.format_lines()
                + f"\n<i>{html_emoji('burst')} Фаст: {html_emoji('yellow')} прокси (туннель OK / SMTP-check не подтвердил) — стартую.</i>",
            )
        return (
            False,
            summary.format_lines()
            + f"\n\n{html_emoji('fail')} <b>Фаст рассыл</b> требует хотя бы один SOCKS5/HTTP прокси (🟢 или 🟡). "
            f"Сейчас все {html_emoji('red')} — замените прокси или нажмите «Проверить прокси».",
        )
    if summary.ok >= 1:
        return True, summary.format_lines()
    if summary.unknown >= 1:
        return (
            True,
            summary.format_lines()
            + "\n<i>Чёткого SMTP OK нет (таймаут/сеть) — рассылка всё равно стартует.</i>",
        )
    return (
        False,
        summary.format_lines()
        + f"\n\n{html_emoji('fail')} Все прокси помечены {html_emoji('red')} после сбоя туннеля при рассылке. "
        f"Замените их или дождитесь «Проверить прокси» ({html_emoji('green')}).",
    )


async def preflight_proxies_for_mailing(
    db_user_id: int,
    *,
    fast: bool = False,
    sticky_proxy_id: int | None = None,
) -> Tuple[bool, ProxyHealthSummary, str]:
    async with db_session() as session:
        if fast:
            summary = await summarize_proxy_health(session, db_user_id)
            if summary.total <= 0:
                ok, detail = mailing_may_start(summary, fast=fast)
                return ok, summary, detail

            if MAIL_FAST_PREFLIGHT_SKIP or MAIL_FAST_PREFLIGHT == "skip":
                ok, detail = mailing_may_start(summary, fast=fast)
                if ok:
                    detail = (
                        summary.format_lines()
                        + f"\n<i>{html_emoji('burst')} Фаст: без ожидания SMTP-check (Loma/residential).</i>"
                    )
                return ok, summary, detail

            from services.smtp_proxy_send import pick_sticky_proxy_for_fast_mailing
            from services.proxy_verify import (
                apply_proxy_check_to_row,
                is_tunnel_only_smtp_check_failure,
                test_proxy_for_add,
                test_proxy_tunnel_only,
            )
            from sqlalchemy import select as sa_select

            px = None
            if sticky_proxy_id is not None:
                px = (
                    await session.execute(
                        sa_select(Proxy).where(
                            Proxy.user_id == int(db_user_id),
                            Proxy.id == int(sticky_proxy_id),
                        )
                    )
                ).scalar_one_or_none()
            if px is None:
                px = await pick_sticky_proxy_for_fast_mailing(session, int(db_user_id))

            if px is None:
                ok, detail = mailing_may_start(summary, fast=fast)
                return ok, summary, detail

            if MAIL_FAST_PREFLIGHT == "tunnel":
                ok_px, info = await test_proxy_tunnel_only(px, timeout=10)
                tunnel_only = is_tunnel_only_smtp_check_failure(info or "")
                if not tunnel_only:
                    apply_proxy_check_to_row(px, ok_px, info or "")
                    await session.commit()
                    summary = await summarize_proxy_health(session, db_user_id)
                else:
                    tunnel_only = True
            else:
                ok_px, info = await test_proxy_for_add(
                    px, smtp_timeout=MAIL_FAST_PREFLIGHT_TIMEOUT, smtp=True
                )
                apply_proxy_check_to_row(px, ok_px, info)
                await session.commit()
                summary = await summarize_proxy_health(session, db_user_id)
                tunnel_only = is_tunnel_only_smtp_check_failure(info or "")

        else:
            summary = await run_proxy_health_check(session, db_user_id)
            tunnel_only = False

    ok, detail = mailing_may_start(summary, fast=fast)
    if fast and not ok and tunnel_only:
        ok = True
        detail = (
            summary.format_lines()
            + f"\n<i>{html_emoji('burst')} Фаст: туннель OK, SMTP-check к Gmail не прошёл — "
            f"рассылка через этот прокси всё равно стартует.</i>"
        )
    if fast and ok and not MAIL_FAST_PREFLIGHT_SKIP and sticky_proxy_id is not None:
        detail = (
            summary.format_lines()
            + f"\n<i>{html_emoji('burst')} Фаст: проверен 1 ротирующий прокси (id=<b>{sticky_proxy_id}</b>), "
            f"таймаут {MAIL_FAST_PREFLIGHT_TIMEOUT}с.</i>"
        )
    elif fast and ok and not MAIL_FAST_PREFLIGHT_SKIP:
        detail = (
            summary.format_lines()
            + f"\n<i>{html_emoji('burst')} Фаст: проверен 1 ротирующий прокси, "
            f"таймаут {MAIL_FAST_PREFLIGHT_TIMEOUT}с.</i>"
        )
    return ok, summary, detail


async def mailing_proxy_watch_loop(
    *,
    tg_user_id: int,
    db_user_id: int,
    bot: Optional[Bot] = None,
    chat_id: Optional[int] = None,
) -> None:
    """Каждые MAIL_PROXY_RECHECK_SEC перепроверяет прокси, пока идёт рассылка."""
    from services.sending_state import get_sending_state

    last_ok = -1
    while True:
        await asyncio.sleep(MAIL_PROXY_RECHECK_SEC)
        st = get_sending_state(tg_user_id)
        if not st or not st.is_running or st.is_stopping:
            break
        # Не держим _PROXY_LOCK параллельно с SMTP-рассылкой — иначе 0/73 «зависает».
        if st.is_running:
            logger.info("skip proxy recheck during mailing tg=%s", tg_user_id)
            continue
        try:
            async with db_session() as session:
                summary = await run_proxy_health_check(session, db_user_id)
        except Exception:
            logger.exception("mailing proxy recheck failed tg=%s", tg_user_id)
            continue

        logger.info(
            "mailing proxy recheck tg=%s %s",
            tg_user_id,
            summary,
        )
        if bot and chat_id and summary.ok != last_ok:
            last_ok = summary.ok
            if summary.ok == 0 and summary.total > 0 and summary.bad == summary.total:
                try:
                    await bot.send_message(
                        int(chat_id),
                        f"{html_emoji('warn')} <b>Перепроверка прокси</b>\n"
                        f"{summary.format_lines()}\n\n"
                        f"<i>Рассылка продолжается — только по {html_emoji('green')}/{html_emoji('yellow')} прокси ({html_emoji('red')} пропускаются).</i>",
                        parse_mode="HTML",
                    )
                except Exception:
                    pass
