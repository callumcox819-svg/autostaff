"""Настройки → Страны: тумблеры + рабочая страна (свои пресеты/домены)."""

from __future__ import annotations

import html
import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from database import Session
from services.enabled_countries import (
    countries_for_settings_ui,
    get_active_country,
    set_active_country,
)
from services.users import get_or_create_user
from utils.ui_emoji import (
    back_inline,
    html_emoji,
    inline_button,
    toast,
    toggle_button,
)

router = Router(name="countries")
logger = logging.getLogger(__name__)


def _countries_kb(active: str) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for cid, label, emoji_key in countries_for_settings_ui():
        working = cid == active
        if working:
            name_btn = toggle_button(True, label, f"country_select:{cid}")
        else:
            name_btn = inline_button(
                emoji_key,
                label,
                callback_data=f"country_select:{cid}",
            )
        rows.append(
            [
                name_btn,
                toggle_button(
                    working,
                    "Вкл" if working else "Выкл",
                    f"country_toggle:{cid}",
                ),
            ]
        )
    rows.append([back_inline("settings_open")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _countries_text(active: str) -> str:
    names = {cid: label for cid, label, _ in countries_for_settings_ui()}
    active_name = names.get(active, active.upper())
    extra = ""
    if active == "de":
        extra = (
            "\nГермания: ссылки на <b>eBay.de</b> через выбранную команду API, "
            "валидация с упором на GMX/WEB.DE."
        )
    elif active == "at":
        extra = (
            "\nАвстрия: HTML по площадке — "
            "<code>willhaben_at</code> / <code>laendleanzeiger_at</code>."
        )
    return (
        f"{html_emoji('compass')} <b>Страны</b>\n\n"
        f"Рабочая: <b>{html.escape(active_name)}</b>\n"
        f"Пресеты, умные пресеты, темы писем и домены — у этой страны.\n"
        f"{extra}\n\n"
        f"Тумблер справа — включить страну. Слева она загорается."
    )


async def _edit(callback: CallbackQuery, text: str, kb: InlineKeyboardMarkup) -> None:
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except TelegramBadRequest:
        try:
            await callback.message.answer(text, reply_markup=kb, parse_mode="HTML")
        except Exception:
            pass


async def _set_working(callback: CallbackQuery, cid: str) -> None:
    async with Session() as session:
        user = await get_or_create_user(session, callback.from_user.id)
        current = await get_active_country(session, user)
        if cid == current:
            await callback.answer(toast("ok", "Уже рабочая"))
            return
        try:
            active = await set_active_country(session, user, cid)
        except ValueError as e:
            await callback.answer(toast("fail", str(e)[:180]), show_alert=True)
            return
    await _edit(callback, _countries_text(active), _countries_kb(active))
    from services.country_scope import country_display_name

    await callback.answer(toast("ok", country_display_name(active)))


@router.callback_query(F.data == "countries_menu")
async def countries_menu(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    async with Session() as session:
        user = await get_or_create_user(session, callback.from_user.id)
        active = await get_active_country(session, user)
    await _edit(callback, _countries_text(active), _countries_kb(active))
    await callback.answer()


@router.callback_query(F.data.startswith("country_select:"))
async def country_select(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    cid = (callback.data or "").split(":", 1)[-1].strip().lower()
    await _set_working(callback, cid)


@router.callback_query(F.data.startswith("country_toggle:"))
async def country_toggle(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    cid = (callback.data or "").split(":", 1)[-1].strip().lower()
    await _set_working(callback, cid)
