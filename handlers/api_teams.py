"""UI: Команды API — список CSM / Evoleum и настройки выбранной команды."""

from __future__ import annotations

import html
import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from database import Session
from services.api_teams import (
    API_TEAMS,
    get_selected_team_id,
    get_team_config,
    set_selected_team_id,
    set_team_field,
    team_label,
)
from services.users import get_or_create_user
from utils.ui_emoji import (
    back_inline,
    html_emoji,
    inline_button,
    toast,
    unicode_fallback,
)

router = Router(name="api_teams")
logger = logging.getLogger(__name__)


class TeamFieldState(StatesGroup):
    waiting = State()


def _teams_list_kb(selected_id: str) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for tid, label in API_TEAMS:
        mark = unicode_fallback("ok") if tid == selected_id else "×"
        rows.append(
            [
                InlineKeyboardButton(text=label, callback_data=f"api_team_open:{tid}"),
                InlineKeyboardButton(text=mark, callback_data=f"api_team_pick:{tid}"),
            ]
        )
    rows.append([back_inline("settings_open")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _teams_list_text(selected_id: str, *, page: str = "1/1") -> str:
    return (
        f"{html_emoji('key')} <b>Команды API</b>\n"
        f"Стр. {html.escape(page)}\n\n"
        f"Выбрана: <b>{html.escape(team_label(selected_id))}</b>\n"
        f"{html_emoji('ok')} — активна для генерации · × — нет"
    )


def _team_detail_kb(team_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [inline_button("settings", "API-ключ", callback_data=f"api_team_edit:{team_id}:api_key")],
            [inline_button("settings", "Team-ключ", callback_data=f"api_team_edit:{team_id}:team_key")],
            [inline_button("settings", "Код сервиса", callback_data=f"api_team_edit:{team_id}:service_code")],
            [inline_button("settings", "Profile ID", callback_data=f"api_team_edit:{team_id}:profile_id")],
            [inline_button("settings", "Тип (card/lk)", callback_data=f"api_team_edit:{team_id}:link_type")],
            [back_inline("api_teams")],
        ]
    )


def _team_detail_text(cfg) -> str:
    key_show = (cfg.api_key or "—").strip() or "—"
    team_show = (cfg.team_key or "—").strip() or "—"
    return (
        f"{html_emoji('key')} <b>{html.escape(cfg.label)}</b>\n\n"
        f"<b>API-ключ:</b> <code>{html.escape(key_show)}</code>\n"
        f"<b>Team-ключ:</b> <code>{html.escape(team_show)}</code>\n"
        f"<b>Код сервиса:</b> <code>{html.escape(cfg.service_code or '—')}</code>\n"
        f"<b>Profile ID:</b> <code>{html.escape(cfg.profile_id or '—')}</code>\n"
        f"<b>Тип:</b> <code>{html.escape(cfg.link_type or 'lk')}</code>"
    )


async def _edit(callback: CallbackQuery, text: str, kb: InlineKeyboardMarkup) -> None:
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except TelegramBadRequest:
        try:
            await callback.message.answer(text, reply_markup=kb, parse_mode="HTML")
        except Exception:
            pass


@router.callback_query(F.data == "api_teams")
async def api_teams_menu(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    async with Session() as session:
        user = await get_or_create_user(session, callback.from_user.id)
        selected = await get_selected_team_id(session, user)
    await _edit(callback, _teams_list_text(selected), _teams_list_kb(selected))
    await callback.answer()


@router.callback_query(F.data.startswith("api_team_pick:"))
async def api_team_pick(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    tid = (callback.data or "").split(":", 1)[-1].strip()
    async with Session() as session:
        user = await get_or_create_user(session, callback.from_user.id)
        try:
            selected = await set_selected_team_id(session, user, tid)
            await session.commit()
        except ValueError:
            await callback.answer(toast("fail", "Неизвестная команда"), show_alert=True)
            return
    await _edit(callback, _teams_list_text(selected), _teams_list_kb(selected))
    await callback.answer(toast("ok", f"Выбрано: {team_label(selected)}"))


@router.callback_query(F.data.startswith("api_team_open:"))
async def api_team_open(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    tid = (callback.data or "").split(":", 1)[-1].strip()
    async with Session() as session:
        user = await get_or_create_user(session, callback.from_user.id)
        try:
            cfg = await get_team_config(session, user, tid)
        except Exception:
            await callback.answer(toast("fail", "Ошибка"), show_alert=True)
            return
    if cfg.team_id not in {t for t, _ in API_TEAMS}:
        await callback.answer(toast("fail", "Неизвестная команда"), show_alert=True)
        return
    await _edit(callback, _team_detail_text(cfg), _team_detail_kb(cfg.team_id))
    await callback.answer()


_FIELD_TITLES = {
    "api_key": "API-ключ",
    "team_key": "Team-ключ (X-Team-Key)",
    "service_code": "Код сервиса",
    "profile_id": "Profile ID",
    "link_type": "Тип (card или lk)",
}


@router.callback_query(F.data.startswith("api_team_edit:"))
async def api_team_edit(callback: CallbackQuery, state: FSMContext) -> None:
    parts = (callback.data or "").split(":")
    if len(parts) != 3:
        await callback.answer()
        return
    _, tid, field = parts
    if field not in _FIELD_TITLES:
        await callback.answer(toast("fail", "Поле"), show_alert=True)
        return
    await state.set_state(TeamFieldState.waiting)
    await state.update_data(team_id=tid, field=field)
    hint = ""
    if field == "link_type":
        hint = "\nОтправь <code>lk</code> или <code>card</code>."
    elif field == "service_code" and tid == "evoleum":
        hint = "\nДля NL обычно: <code>marktplaats_nl</code>."
    await _edit(
        callback,
        f"{html_emoji('settings')} <b>{html.escape(_FIELD_TITLES[field])}</b>\n"
        f"Команда: <b>{html.escape(team_label(tid))}</b>\n\n"
        f"Пришли новое значение одним сообщением.{hint}",
        InlineKeyboardMarkup(
            inline_keyboard=[[back_inline(f"api_team_open:{tid}", text="Отмена")]]
        ),
    )
    await callback.answer()


@router.message(TeamFieldState.waiting)
async def api_team_field_save(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    tid = str(data.get("team_id") or "")
    field = str(data.get("field") or "")
    raw = (message.text or "").strip()
    if not tid or not field:
        await state.clear()
        return
    async with Session() as session:
        user = await get_or_create_user(session, message.from_user.id)
        try:
            await set_team_field(session, user, tid, field, raw)
            await session.commit()
            cfg = await get_team_config(session, user, tid)
        except ValueError as e:
            await message.answer(f"{html_emoji('fail')} {html.escape(str(e))}", parse_mode="HTML")
            return
    await state.clear()
    await message.answer(
        f"{html_emoji('ok')} Сохранено.\n\n{_team_detail_text(cfg)}",
        reply_markup=_team_detail_kb(tid),
        parse_mode="HTML",
    )
