"""Настройки → тумблер Авто-рассылка: очередь уходит сама, без /send."""

from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace

from aiogram import F, Router
from aiogram.types import CallbackQuery

from database import db_session
from services.autosend import (
    auto_send_paused,
    clear_auto_send_pause,
    get_auto_send_chat_id,
    is_auto_send_on,
    set_auto_send_chat_id,
    set_auto_send_on,
)
from services.users import get_or_create_user
from utils.bg_jobs import is_running as bg_is_running
from utils.bg_jobs import start as bg_start
from utils.callback_safe import callback_answer_safe
from utils.ui_emoji import toast

router = Router(name="autosend")
logger = logging.getLogger(__name__)

_JOB = "autosend"


async def kick_autosend(bot, chat_id: int, tg_id: int, *, force: bool = False) -> None:
    """Поднять цикл, если тумблер включён. force — сразу после валидации (без паузы /stop)."""
    async with db_session() as session:
        user = await get_or_create_user(session, int(tg_id))
        if not await is_auto_send_on(session, user):
            return
        await set_auto_send_chat_id(session, user, int(chat_id))
    if force:
        clear_auto_send_pause(int(tg_id))
    if bg_is_running(int(tg_id), _JOB):
        return
    bg_start(int(tg_id), _JOB, _autosend_loop(bot, int(chat_id), int(tg_id)))


async def _queue_count(tg_id: int) -> int:
    from handlers.send import _get_targets_count

    async with db_session() as session:
        user = await get_or_create_user(session, int(tg_id))
        return int(await _get_targets_count(session, int(user.id)))


def _mailing_busy(tg_id: int) -> bool:
    from handlers.send import get_sending_state

    st = get_sending_state(int(tg_id))
    return bool(st and st.is_running and not st.is_stopping)


async def _autosend_loop(bot, chat_id: int, tg_id: int) -> None:
    fails = 0
    try:
        while True:
            async with db_session() as session:
                user = await get_or_create_user(session, tg_id)
                if not await is_auto_send_on(session, user):
                    return
            if auto_send_paused(tg_id):
                await asyncio.sleep(5)
                continue
            if _mailing_busy(tg_id):
                await asyncio.sleep(12)
                continue
            pending = 0
            try:
                pending = await _queue_count(tg_id)
            except Exception:
                logger.exception("autosend queue count tg=%s", tg_id)
                await asyncio.sleep(20)
                continue
            if pending <= 0:
                fails = 0
                await asyncio.sleep(18)
                continue
            try:
                await start_sending_from_bot(bot, chat_id, tg_id)
            except Exception:
                logger.exception("autosend start tg=%s", tg_id)
            await asyncio.sleep(8)
            if not _mailing_busy(tg_id):
                fails += 1
                await asyncio.sleep(min(120, 15 * fails))
            else:
                fails = 0
    except asyncio.CancelledError:
        raise


async def start_sending_from_bot(bot, chat_id: int, tg_user_id: int) -> None:
    from handlers.send import _start_sending_inner
    from utils.ui_emoji import html_emoji as he

    status_msg = await bot.send_message(
        chat_id,
        f"{he('wait')} Авто-рассылка: проверяю очередь…",
        parse_mode="HTML",
    )
    dummy = SimpleNamespace(
        bot=bot,
        chat=SimpleNamespace(id=int(chat_id)),
        from_user=SimpleNamespace(id=int(tg_user_id)),
    )

    async def _answer(*args, **kwargs):
        return await bot.send_message(chat_id, *args, **kwargs)

    dummy.answer = _answer
    await _start_sending_inner(
        message=dummy,
        status_msg=status_msg,
        tg_user_id=int(tg_user_id),
        chat_id=int(chat_id),
        bot=bot,
    )


@router.callback_query(F.data == "auto_send_toggle")
async def auto_send_toggle(callback: CallbackQuery) -> None:
    from handlers.settings import _cq_edit_text, _settings_menu_kb_for_user, _settings_title_for_user

    tg_id = int(callback.from_user.id)
    chat_id = int(callback.message.chat.id)
    async with db_session() as session:
        user = await get_or_create_user(session, tg_id)
        on = not await is_auto_send_on(session, user)
        await set_auto_send_on(session, user, on)
        if on:
            await set_auto_send_chat_id(session, user, chat_id)
    if on:
        clear_auto_send_pause(tg_id)
        kick = True
        await callback_answer_safe(callback, toast("ok", "Авто-рассылка вкл"))
    else:
        from utils.bg_jobs import cancel as bg_cancel

        bg_cancel(tg_id, _JOB)
        kick = False
        await callback_answer_safe(callback, toast("ok", "Авто-рассылка выкл"))
    kb = await _settings_menu_kb_for_user(tg_id)
    await _cq_edit_text(
        callback,
        await _settings_title_for_user(tg_id),
        reply_markup=kb,
        parse_mode="HTML",
    )
    if kick:
        await kick_autosend(callback.bot, chat_id, tg_id, force=True)
