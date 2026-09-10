"""Главное меню: inline-кнопки + /menu (без залипающей клавиатуры снизу)."""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from keyboards.main_menu import hide_reply_keyboard, main_menu_inline_kb_for
from utils.ui_emoji import html_emoji

router = Router(name="main_menu")
logger = logging.getLogger(__name__)


async def show_main_menu(message: Message, *, tg_user_id: int) -> None:
    kb = await main_menu_inline_kb_for(tg_user_id)
    await message.answer(
        f"{html_emoji('burst')} <b>Меню</b>\n"
        "Кнопки под сообщением — чат на телефоне не перекрывают.\n"
        "Или ⌘ у поля ввода: /menu /send /stop /stat /settings",
        reply_markup=kb,
        parse_mode="HTML",
    )


@router.message(Command("menu"))
async def cmd_menu(message: Message) -> None:
    await message.answer("⌨️", reply_markup=hide_reply_keyboard())
    await show_main_menu(message, tg_user_id=int(message.from_user.id))


@router.callback_query(F.data.startswith("menu:"))
async def menu_callback(callback: CallbackQuery, state: FSMContext) -> None:
    action = (callback.data or "").split(":", 1)[-1].strip()
    tg_id = int(callback.from_user.id)
    msg = callback.message
    try:
        await callback.answer()
    except Exception:
        pass
    if not msg:
        return

    if action == "settings":
        from handlers.settings import settings_open_cb

        return await settings_open_cb(callback, state)

    if action == "send":
        from handlers.send import start_sending

        return await start_sending(msg, tg_user_id=tg_id)

    if action == "stop":
        from handlers.stopsend import cmd_stopsend_for

        return await cmd_stopsend_for(msg, tg_user_id=tg_id)

    if action == "status":
        from handlers.status import cmd_statussend_for

        return await cmd_statussend_for(msg, tg_user_id=tg_id)

    if action == "test_mail":
        from handlers.test_mail import test_mail_open_cb

        return await test_mail_open_cb(callback, state)

    if action == "quick_add":
        from handlers.accounts import quick_gmail_open_cb

        return await quick_gmail_open_cb(callback, state)

    if action == "admin":
        from handlers.admin_panel import open_admin_for

        return await open_admin_for(msg, tg_user_id=tg_id)

    await msg.answer(f"{html_emoji('fail')} Неизвестный пункт меню.")
