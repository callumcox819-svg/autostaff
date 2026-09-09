"""Меню «Темы писем»: список + random/fixed + OFFER."""

from __future__ import annotations

from html import escape

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from database import db_session
from services.mailing_subjects import (
    PAGE_SIZE,
    clamp_page,
    get_fixed_index,
    get_subject_lines,
    get_subject_mode,
    mode_label,
    page_count,
    parse_subject_lines,
    set_fixed_index,
    set_subject_lines,
    set_subject_mode,
)
from services.users import get_or_create_user
from utils.ui_emoji import back_inline, html_emoji, inline_button

router = Router(name="mail_subjects")


class MailSubjectsEdit(StatesGroup):
    waiting_list = State()


def _btn_label(idx: int, text: str, *, fixed: bool, mode: str) -> str:
    raw = " ".join((text or "").split()).strip() or f"#{idx + 1}"
    if len(raw) > 48:
        raw = raw[:47] + "…"
    mark = "✓ " if mode == "fixed" and fixed else ""
    return f"{mark}{idx + 1}. {raw}"


async def build_mail_subjects_view(tg_user_id: int, page: int = 0) -> tuple[str, InlineKeyboardMarkup]:
    async with db_session() as session:
        user = await get_or_create_user(session, tg_user_id)
        lines = await get_subject_lines(session, user)
        mode = await get_subject_mode(session, user)
        fixed_idx = await get_fixed_index(session, user)

    total = len(lines)
    pg = clamp_page(page, total)
    pages = page_count(total)
    start = pg * PAGE_SIZE
    chunk = lines[start : start + PAGE_SIZE]

    text = (
        f"{html_emoji('presets')} <b>Темы писем</b>\n\n"
        f"<b>Режим:</b> {escape(mode_label(mode))}\n"
        f"<b>Строк в списке:</b> {total}\n\n"
        "Кнопка со строкой — сделать её фиксированной темой.\n"
        "«Случайный» — каждый раз любая строка.\n\n"
        f"<b>Переменная:</b> <code>OFFER</code> / <code>{{{{OFFER}}}}</code> — название товара."
    )

    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(
                text=("✓ Случайный" if mode == "random" else "Случайный"),
                callback_data="msubj:mode:random",
            ),
            InlineKeyboardButton(
                text=("✓ Только фикс." if mode == "fixed" else "Только фикс."),
                callback_data="msubj:mode:fixed",
            ),
        ],
        [
            inline_button("settings", "Изменить список", callback_data="msubj:edit"),
        ],
    ]

    for i, line in enumerate(chunk):
        abs_i = start + i
        rows.append(
            [
                InlineKeyboardButton(
                    text=_btn_label(abs_i, line, fixed=(abs_i == fixed_idx), mode=mode),
                    callback_data=f"msubj:pick:{abs_i}",
                )
            ]
        )

    nav: list[InlineKeyboardButton] = []
    if pg > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"msubj:page:{pg - 1}"))
    nav.append(InlineKeyboardButton(text=f"{pg + 1}/{pages}", callback_data="msubj:noop"))
    if pg < pages - 1:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"msubj:page:{pg + 1}"))
    nav.append(InlineKeyboardButton(text="🔄", callback_data=f"msubj:page:{pg}"))
    rows.append(nav)

    rows.append([back_inline("settings_open")])
    return text, InlineKeyboardMarkup(inline_keyboard=rows)


async def _edit_menu(callback: CallbackQuery, page: int = 0) -> None:
    text, kb = await build_mail_subjects_view(callback.from_user.id, page)
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        await callback.message.answer(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data.in_({"mail_subjects", "themes_menu"}))
async def mail_subjects_open(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await _edit_menu(callback, 0)
    await callback.answer()


@router.callback_query(F.data == "msubj:noop")
async def mail_subjects_noop(callback: CallbackQuery) -> None:
    await callback.answer()


@router.callback_query(F.data.startswith("msubj:page:"))
async def mail_subjects_page(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    try:
        page = int((callback.data or "").split(":")[-1])
    except ValueError:
        page = 0
    await _edit_menu(callback, page)
    await callback.answer()


@router.callback_query(F.data.startswith("msubj:mode:"))
async def mail_subjects_mode(callback: CallbackQuery, state: FSMContext) -> None:
    mode = (callback.data or "").split(":")[-1]
    if mode not in ("random", "fixed"):
        await callback.answer()
        return
    async with db_session() as session:
        user = await get_or_create_user(session, callback.from_user.id)
        lines = await get_subject_lines(session, user)
        if mode == "fixed" and not lines:
            await callback.answer("Сначала задай список тем.", show_alert=True)
            return
        await set_subject_mode(session, user, mode)  # type: ignore[arg-type]
    await _edit_menu(callback, 0)
    await callback.answer("Случайный" if mode == "random" else "Только фикс.")


@router.callback_query(F.data.startswith("msubj:pick:"))
async def mail_subjects_pick(callback: CallbackQuery, state: FSMContext) -> None:
    try:
        idx = int((callback.data or "").split(":")[-1])
    except ValueError:
        await callback.answer()
        return
    page = 0
    async with db_session() as session:
        user = await get_or_create_user(session, callback.from_user.id)
        lines = await get_subject_lines(session, user)
        if not lines or idx < 0 or idx >= len(lines):
            await callback.answer("Строка не найдена.", show_alert=True)
            return
        await set_fixed_index(session, user, idx)
        await set_subject_mode(session, user, "fixed")
        page = clamp_page(idx // PAGE_SIZE, len(lines))
    await _edit_menu(callback, page)
    await callback.answer("Фиксированная тема")


@router.callback_query(F.data == "msubj:edit")
async def mail_subjects_edit(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(MailSubjectsEdit.waiting_list)
    await state.update_data(msubj_chat=callback.message.chat.id if callback.message else None)
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[back_inline("mail_subjects")]],
    )
    txt = (
        f"{html_emoji('write')} <b>Изменить список тем</b>\n\n"
        "Пришли список <b>по одной теме в строке</b>, например:\n"
        "<code>Hello\n"
        "Hi\n"
        "Nog beschikbaar?\n"
        "Is OFFER still available?</code>\n\n"
        "Старый список будет <b>заменён</b> целиком.\n"
        f"<code>OFFER</code> / <code>{{{{OFFER}}}}</code> — название товара."
    )
    try:
        await callback.message.edit_text(txt, reply_markup=kb, parse_mode="HTML")
    except Exception:
        await callback.message.answer(txt, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@router.message(MailSubjectsEdit.waiting_list, F.text)
async def mail_subjects_set_list(message: Message, state: FSMContext) -> None:
    lines = parse_subject_lines(message.text or "")
    if not lines:
        await message.answer(
            f"{html_emoji('fail')} Пустой список. Пришли хотя бы одну строку.",
            parse_mode="HTML",
        )
        return

    async with db_session() as session:
        user = await get_or_create_user(session, message.from_user.id)
        await set_subject_lines(session, user, lines)
        mode = await get_subject_mode(session, user)
        if mode == "fixed":
            await set_fixed_index(session, user, 0)

    await state.clear()
    text, kb = await build_mail_subjects_view(message.from_user.id, 0)
    await message.answer(
        f"{html_emoji('ok')} Список обновлён: <b>{len(lines)}</b> тем(ы).\n\n{text}",
        reply_markup=kb,
        parse_mode="HTML",
    )
