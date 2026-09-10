from __future__ import annotations
from utils.ui_emoji import html_emoji, inline_button, menu_path, toast, msg_fail, msg_ok, msg_wait, msg_warn

import logging
import os

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery

from sqlalchemy import select, func, or_

from database import db_session
from models import OfferEmail, Offer, EmailAccount, IncomingMail
from services.users import get_or_create_user
from services.sending_state import get_sending_state, SendingState
from keyboards.main_menu import is_status_trigger

router = Router()
logger = logging.getLogger(__name__)

_ERROR_HINTS = {
    "PROXY_ERROR": "Ошибка прокси (проверь логин/порт в «Прокси»)",
    "SMTP_TIMEOUT": "Таймаут SMTP через прокси — попробуйте другой прокси или увеличьте SMTP_TIMEOUT_SEC",
    "ACCOUNT_INVALID_CREDENTIALS": "Неверный пароль почты (нужен пароль приложения)",
    "ACCOUNT_WEB_LOGIN_REQUIRED": "Gmail просит войти в браузере — разблокируйте аккаунт",
    "ACCOUNT_RATE_LIMIT": "Лимит отправки Gmail — сделайте паузу или смените аккаунт",
    "ACCOUNT_SOFT_CAP": "Мягкий лимит писем с ящика за час — пауза или другой аккаунт",
    "ACCOUNT_BLOCKED": "Почтовый аккаунт заблокирован для отправки",
    "RECIPIENT_DEAD": "Адрес не существует (удалён из очереди)",
    "SMTP_ACCEPTED_NOT_IN_SENT": "SMTP принял, но в «Отправленных» нет — адрес остаётся в очереди",
    "RECIPIENT_REFUSED": "Сервер отклонил письмо на этот адрес",
    "TG_ERROR": "Сбой Telegram (сеть бота)",
    "NO_ACCOUNTS": "Нет активных аккаунтов",
}


def _humanize_send_error(raw: str) -> str:
    """Короткое описание ошибки рассылки для /stat."""
    s = (raw or "").strip()
    if not s or s == "-":
        return ""

    kind = s.split("|", 1)[0].split(":", 1)[0].strip().upper()
    hint = _ERROR_HINTS.get(kind, "")
    detail = s.replace("\n", " ").strip()
    if len(detail) > 220:
        detail = detail[:220] + "…"
    if "no_active_proxy" in s.lower():
        hint = "Нет активного прокси в БД (добавь SOCKS5/HTTP или «Проверить прокси»)"
    if hint:
        return f"{hint}\n<code>{detail}</code>"
    return f"<code>{detail}</code>"


def tg_answer_safe(obj: Message | CallbackQuery, text: str, **kwargs):
    """Безопасный ответ (Message -> answer, CallbackQuery -> message.answer)."""
    try:
        if isinstance(obj, CallbackQuery):
            return obj.message.answer(text, **kwargs)
        return obj.answer(text, **kwargs)
    except Exception as e:
        logger.exception("tg_answer_safe error: %s", e)
        return None


def render_status_text(
    st: SendingState | dict | None,
    *,
    offers_total: int | None = None,
    pending_now: int | None = None,
    accounts_total: int | None = None,
    accounts_active: int | None = None,
    inbox_bounces: int | None = None,
    inbox_seller_hits: int | None = None,
) -> str:
    """Статус рассылки + данные в БД (всегда, даже если рассылка не запущена)."""
    # st может быть dict (на всякий)
    if isinstance(st, dict):
        # максимально мягко
        running = bool(st.get("is_running") or st.get("running"))
        sent = int(st.get("sent_count") or st.get("sent") or 0)
        failed = int(st.get("failed_count") or st.get("errors") or 0)
        mode = (st.get("last_status") or "-").upper() or "-"
        if mode == "BURST" or st.get("fast_mailing"):
            mode = "BURST"
        acc_t = st.get("accounts_total")
        acc_a = st.get("accounts_active")
        last_err = (st.get("last_error") or "").strip()
        last_to = (st.get("last_failed_to") or "").strip()
        current_to = (st.get("current_to") or "").strip()
        total_st = int(st.get("total_targets") or 0)
    elif st:
        running = bool(getattr(st, "is_running", False) or getattr(st, "running", False))
        sent = int(getattr(st, "sent_count", 0) or getattr(st, "sent", 0) or 0)
        failed = int(getattr(st, "failed_count", 0) or getattr(st, "errors", 0) or 0)
        mode = (getattr(st, "last_status", None) or "-").upper()
        if mode == "BURST" or getattr(st, "fast_mailing", False):
            mode = "BURST"
        acc_t = getattr(st, "accounts_total", None)
        acc_a = getattr(st, "accounts_active", None)
        last_err = (getattr(st, "last_error", "") or "").strip()
        last_to = (getattr(st, "last_failed_to", "") or "").strip()
        current_to = (getattr(st, "current_to", "") or "").strip()
        total_st = int(getattr(st, "total_targets", 0) or 0)
    else:
        running = False
        sent = failed = 0
        mode = "-"
        acc_t = acc_a = None
        last_err = ""
        last_to = ""
        current_to = ""
        total_st = 0

    # приоритет: свежие значения из БД
    if accounts_total is not None:
        acc_t = accounts_total
    if accounts_active is not None:
        acc_a = accounts_active

    acc_t = int(acc_t or 0)
    acc_a = int(acc_a or 0)

    # pending_now - сколько реально осталось в БД для отправки
    if pending_now is None:
        pending_now = int(getattr(st, "total_targets", 0) or getattr(st, "total", 0) or 0)
    pending_now = int(pending_now)
    offers_total = int(offers_total or 0)

    if running:
        run_line = f"{html_emoji('green')} Рассылка запущена"
    else:
        run_line = "Сейчас рассылка не запущена."

    last_err_line = ""
    if int(failed) > 0:
        if last_err and last_err not in ("-", ""):
            who = f" → <code>{last_to}</code>" if last_to else ""
            last_err_line = f"\n\n<b>Последняя ошибка</b>{who}\n{_humanize_send_error(last_err)}"
        else:
            last_err_line = (
                "\n\n<i>Были ошибки, но текст последней уже не в памяти — "
                "после следующей ошибки снова появится здесь.</i>"
            )

    progress_line = ""
    total_run = total_st if total_st > 0 else (pending_now + sent + failed)
    processed = sent + failed
    if running:
        if current_to:
            progress_line = (
                f"\n{html_emoji('wait')} Сейчас: <code>{current_to}</code>\n"
                f"Прогресс: <b>{processed}/{total_run or '?'}</b> ({html_emoji('ok')} {sent} · {html_emoji('fail')} {failed})"
            )
        elif total_run > 0:
            progress_line = (
                f"\nПрогресс: <b>{processed}/{total_run}</b> "
                f"({html_emoji('ok')} {sent} · {html_emoji('fail')} {failed} · в очереди {pending_now})"
            )
        elif pending_now > 0:
            progress_line = f"\nПрогресс: <b>{sent}/{pending_now}</b>"

    inbox_line = ""
    if inbox_bounces is not None and inbox_seller_hits is not None:
        ib = int(inbox_bounces)
        ish = int(inbox_seller_hits)
        inbox_line = (
            f"\n\n<b>Входящие в БД</b>\n"
            f"{html_emoji('restore')} Отбои (mailer-daemon): <b>{ib}</b>\n"
            f"{html_emoji('green')} Ответ продавца (email в базе): <b>{ish}</b>\n"
            "<i>Много отбоев при нуле «продавец» — плохая база или прокси, не «тишина».</i>"
        )

    verify_hint = ""
    if os.getenv("MAIL_VERIFY_SENT", "0").strip().lower() not in ("1", "true", "yes", "on"):
        verify_hint = (
            "\n<i>💡 MAIL_VERIFY_SENT=1 — в «отправлено» только письма в папке Sent.</i>"
        )

    return (
        f"{html_emoji('status')} <b>Статус рассылки</b>\n\n"
        f"{run_line}\n"
        f"Режим: <b>{mode}</b>\n"
        f"Отправлено (SMTP): <b>{sent}</b>\n"
        f"Ошибок отправки: <b>{failed}</b>"
        f"{progress_line}"
        f"{last_err_line}\n\n"
        "<b>В базе данных</b>\n"
        f"{html_emoji('presets')} Объявлений: <b>{offers_total}</b>\n"
        f"{html_emoji('email')} Email в очереди: <b>{pending_now}</b>\n"
        f"{html_emoji('email')} Аккаунты: <b>{acc_a}/{acc_t}</b> активных"
        f"{inbox_line}"
        f"{verify_hint}"
    )


async def _collect_db_stats(
    tg_user_id: int,
) -> tuple[int, int, int, int, int, int]:
    """(offers, pending, acc_total, acc_active, inbox_bounces, inbox_seller_hits)"""
    async with db_session() as session:
        db_user = await get_or_create_user(session, tg_user_id)
        db_user_id = db_user.id

        offers_total = (
            await session.execute(
                select(func.count(Offer.id)).where(Offer.user_id == db_user_id)
            )
        ).scalar() or 0

        pending_now = (
            await session.execute(
                select(func.count(OfferEmail.id))
                .select_from(OfferEmail)
                .join(Offer, OfferEmail.offer_id == Offer.id)
                .where(Offer.user_id == db_user_id)
            )
        ).scalar() or 0

        accounts_total = (
            await session.execute(
                select(func.count(EmailAccount.id)).where(EmailAccount.user_id == db_user_id)
            )
        ).scalar() or 0

        accounts_active = (
            await session.execute(
                select(func.count(EmailAccount.id)).where(
                    EmailAccount.user_id == db_user_id,
                    EmailAccount.status == "active",
                )
            )
        ).scalar() or 0

        inbox_bounces = (
            await session.execute(
                select(func.count(IncomingMail.id)).where(
                    IncomingMail.user_id == db_user_id,
                    func.lower(IncomingMail.from_email).like("%mailer-daemon%"),
                )
            )
        ).scalar() or 0

        inbox_seller_hits = (
            await session.execute(
                select(func.count(IncomingMail.id)).where(
                    IncomingMail.user_id == db_user_id,
                    or_(
                        IncomingMail.resolved_offer_email_id.is_not(None),
                        IncomingMail.mailing_bound.is_(True),
                    ),
                )
            )
        ).scalar() or 0

        return (
            int(offers_total),
            int(pending_now),
            int(accounts_total),
            int(accounts_active),
            int(inbox_bounces),
            int(inbox_seller_hits),
        )


@router.message(Command("imap_diag"))
async def cmd_imap_diag(message: Message) -> None:
    """Проверка: жив ли IMAP-воркер и есть ли входящие в БД."""
    tg_user_id = message.from_user.id
    wait_msg = await message.answer(f"{html_emoji('wait')} Смотрю IMAP и входящие в БД…")
    async with db_session() as session:
        from services.incoming_mail_worker import incoming_mail_diag_merged

        snap = await incoming_mail_diag_merged(session)
        user = await get_or_create_user(session, tg_user_id)
        accs = (
            await session.execute(
                select(EmailAccount).where(EmailAccount.user_id == int(user.id))
            )
        ).scalars().all()
        incoming_total = (
            await session.execute(
                select(func.count(IncomingMail.id)).where(IncomingMail.user_id == int(user.id))
            )
        ).scalar() or 0

        from services.incoming_mail_stats import build_incoming_breakdown, format_incoming_breakdown_html

        breakdown = await build_incoming_breakdown(session, int(user.id))
        breakdown_html = format_incoming_breakdown_html(breakdown)

    src = snap.get("diag_source") or "—"
    host = snap.get("worker_host") or "—"
    hb = snap.get("remote_heartbeat_ago_sec")
    if hb is None:
        hb = snap.get("scheduler_last_tick_ago_sec")
    hb_line = f", пульс <b>{hb}</b>s назад" if hb is not None else ""
    lines = [
        "<b>IMAP</b>",
        f"Воркер: <code>{src}</code> · <code>{host}</code>{hb_line}",
        f"Режим: <code>{snap.get('scheduler', '—')}</code>, "
        f"интервал ящика: <code>{snap.get('per_account_interval_sec', '—')}s</code>, "
        f"пауза рассылки: <code>{snap.get('mailing_pause', '—')}</code>",
        f"Параллельно: <b>{snap.get('max_concurrent', '—')}</b>, опрос ~<b>{snap.get('poll_fallback_sec', 20)}</b> с",
        f"Входящих в БД (всего): <b>{incoming_total}</b>",
    ]
    if snap.get("backoff_sec_by_account"):
        lines.append(
            f"{html_emoji('warn')} Пауза после ошибок IMAP (acc_id→сек): <code>{snap['backoff_sec_by_account']}</code>"
        )
    if not accs:
        lines.append(f"\n{html_emoji('fail')} Нет почтовых аккаунтов — IMAP не к чему подключаться.")
    else:
        blocked_accs = [
            a for a in accs if (a.status or "").strip().lower() == "smtp_blocked"
        ]
        if blocked_accs:
            lines.append(
                f"\n<b>{html_emoji('yellow')} SMTP заблокировано ({len(blocked_accs)})</b> — только IMAP, рассылка снята:"
            )
            for a in blocked_accs[:12]:
                err = ((a.last_error or "").strip()[:80] or "Message blocked / лимит")
                lines.append(f"• <code>{a.email}</code> — <i>{err}</i>")
            if len(blocked_accs) > 12:
                lines.append(f"… и ещё {len(blocked_accs) - 12}")

        lines.append("\n<b>Аккаунты:</b>")
        for a in accs[:15]:
            st = (a.status or "—").strip()
            uid = getattr(a, "last_seen_uid", None)
            bo = (snap.get("backoff_sec_by_account") or {}).get(int(a.id))
            extra = f", пауза IMAP {bo}с" if bo else ""
            lines.append(
                f"• <code>{a.email}</code> — {st}, last_uid={uid if uid is not None else 'новый'}{extra}"
            )
        if len(accs) > 15:
            lines.append(f"… и ещё {len(accs) - 15}")
    lines.append(breakdown_html)
    lines.append(
        "\n<i>Тест: ответьте на письмо рассылки → ~30 с карточка в TG. "
        "mailer-daemon (Message blocked) — карточка в TG + ящик smtp_blocked. "
        "Gmail Spam не читаем.</i>"
    )
    text = "\n".join(lines)
    try:
        await wait_msg.edit_text(text, parse_mode="HTML")
    except Exception:
        await message.answer(text, parse_mode="HTML")


@router.message(Command("stat", "status", "statussend"))
@router.message(F.text.func(lambda m: is_status_trigger(getattr(m, "text", None))))
async def cmd_statussend(message: Message) -> None:
    await cmd_statussend_for(message, tg_user_id=int(message.from_user.id))


async def cmd_statussend_for(message: Message, *, tg_user_id: int) -> None:
    st = get_sending_state(int(tg_user_id))

    # Быстрый отклик, пока считаем БД (рассылка не блокирует, но /stat тяжёлый на SQLite).
    wait_msg = await message.answer(f"{html_emoji('wait')} Считаю статистику…")

    offers_total, pending_now, acc_total, acc_active, inbox_bounces, inbox_seller = (
        await _collect_db_stats(int(tg_user_id))
    )

    text = render_status_text(
        st,
        offers_total=offers_total,
        pending_now=pending_now,
        accounts_total=acc_total,
        accounts_active=acc_active,
        inbox_bounces=inbox_bounces,
        inbox_seller_hits=inbox_seller,
    )
    try:
        await wait_msg.edit_text(text, parse_mode="HTML")
    except Exception:
        await message.answer(text, parse_mode="HTML")
