"""Ключ API и профиль для генерации ссылок."""

from __future__ import annotations

import html

from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.exceptions import TelegramBadRequest

from database import Session
from region import AQUA_DEFAULT_SERVICE
from services.users import get_or_create_user
from services.aqua_keys import (
    AQUA_PROFILE_ADDRESS_KEY,
    AQUA_PROFILE_NAME_KEY,
    AQUA_PROFILE_TITLE_KEY,
    AQUA_SERVICE_CHOICES,
    AQUA_SERVICE_KEY,
    AQUA_USER_API_KEY_SETTING,
    aqua_service_label,
    aqua_service_matches,
    get_user_aqua_service,
    get_user_aqua_user_key_async,
    get_user_profile_address,
    get_user_profile_buyer_name,
    get_user_profile_title,
    normalize_aqua_api_key,
    normalize_aqua_service,
    user_profile_fields_complete,
)
from services.gag_domains import (
    domain_mode_menu_options,
    get_user_gag_domain_mode,
    profile_domain_label,
    set_user_gag_domain_mode,
)
from services.aqua_network import AquaError, generate_api_base, generate_api_configured, verify_gag_auth
from services.user_settings import get_user_setting, set_user_setting
from utils.secrets import clean_secret
from utils.ui_emoji import html_emoji, inline_button, back_inline, back_kb, menu_path, toast, msg_fail, msg_ok, msg_wait, msg_warn, unicode_fallback

router = Router(name="api_keys")


class KeysState(StatesGroup):
    waiting_value = State()


class ProfileState(StatesGroup):
    title = State()
    buyer_name = State()
    address = State()


def _back_kb() -> InlineKeyboardMarkup:
    return back_kb("settings_open")


def profile_screen_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [inline_button("edit", "Заполнить / изменить", callback_data="aqua_profile_create")],
            [inline_button("compass", "Сервис", callback_data="aqua_service_pick")],
            [inline_button("link", "Домен генерации", callback_data="aqua_domain_pick")],
            [back_inline("settings_open")],
            [inline_button("hide", "Скрыть", callback_data="aqua_hide")],
        ]
    )


def _domain_mode_kb(current: str) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for code, label in domain_mode_menu_options():
        icon = "green" if code == current else "yellow"
        rows.append([
            inline_button(icon, label, callback_data=f"aqua_domain_set:{code}"),
        ])
    rows.append([back_inline("api_team_open:gag")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _domain_menu_text(mode: str) -> str:
    _ = mode
    return (
        f"{html_emoji('link')} <b>Домен генерации</b>\n\n"
        f"• {html_emoji('profile')} <b>Домен команды</b> — без поля <code>domain</code> в API\n"
        f"• {html_emoji('edit')} <b>Домен 1–4</b> — в API: "
        f"<code>5</code>, <code>6</code>, <code>7</code>, <code>8</code> (слот + 4)"
    )


def service_picker_kb(current: str) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for code in AQUA_SERVICE_CHOICES:
        label = aqua_service_label(code)
        mark = f"{unicode_fallback('ok')} " if aqua_service_matches(current, code) else ""
        rows.append([
            InlineKeyboardButton(
                text=f"{mark}{label}".strip(),
                callback_data=f"aqua_service_set:{code}",
            )
        ])
    rows.append([back_inline("aqua_show:profile")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def key_screen_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [inline_button("wrench", "Установить ключ", callback_data="aqua_set:user_key")],
            [inline_button("search", "Проверить ключ", callback_data="aqua_test_keys")],
            [back_inline("settings_open")],
            [inline_button("hide", "Скрыть", callback_data="aqua_hide")],
        ]
    )


def _show_full(key: str | None) -> str:
    return (key or "—").strip() or "—"


def _field_line(label: str, value: str) -> str:
    v = (value or "").strip() or "—"
    return f"{label}: <code>{v}</code>"


async def _render_profile_screen(callback: CallbackQuery) -> None:
    async with Session() as session:
        user = await get_or_create_user(session, callback.from_user.id)
        raw_svc = (await get_user_setting(session, user, AQUA_SERVICE_KEY) or "").strip()
        if not normalize_aqua_service(raw_svc):
            default_svc = normalize_aqua_service(AQUA_DEFAULT_SERVICE) or AQUA_DEFAULT_SERVICE
            await set_user_setting(session, user, AQUA_SERVICE_KEY, default_svc)
        title = await get_user_profile_title(session, user)
        buyer = await get_user_profile_buyer_name(session, user)
        addr = await get_user_profile_address(session, user)
        service = await get_user_aqua_service(session, user)
        mode = await get_user_gag_domain_mode(session, user)
        complete = await user_profile_fields_complete(session, user)
        await session.commit()
        domain_line = profile_domain_label(mode)
        status = (
            f"{html_emoji('green')} готов к генерации"
            if complete
            else f"{html_emoji('yellow')} заполните все поля"
        )
        text = (
            f"{html_emoji('profile')} <b>Профиль</b>\n\n"
            "Эти данные уходят в сгенерированную ссылку.\n\n"
            f"{_field_line('Название профиля', title)}\n"
            f"{_field_line('Имя получателя', buyer)}\n"
            f"{_field_line('Адрес доставки', addr)}\n"
            f"{_field_line('Сервис', aqua_service_label(service))}\n"
            f"{_field_line('Домен генерации', domain_line)}\n\n"
            f"Статус: {status}"
        )
    try:
        await callback.message.edit_text(text, reply_markup=profile_screen_kb(), parse_mode="HTML")
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            raise


async def _render_key_screen(callback: CallbackQuery) -> None:
    async with Session() as session:
        user = await get_or_create_user(session, callback.from_user.id)
        user_key = await get_user_aqua_user_key_async(session, user)
    base_ok = generate_api_configured()
    base_show = generate_api_base() or "—"
    ok = html_emoji("ok")
    fail = html_emoji("fail")
    text = (
        f"{html_emoji('key')} <b>API-ключ</b>\n\n"
        f"Статус: {ok if user_key else fail} {'задан' if user_key else 'не задан'}\n"
        f"<code>{_show_full(user_key)}</code>\n\n"
        f"Сервер: {ok if base_ok else fail}\n"
        f"<code>{html.escape(base_show)}</code>"
    )
    await callback.message.edit_text(text, reply_markup=key_screen_kb(), parse_mode="HTML")



@router.callback_query(F.data == "aqua_hide")
async def aqua_hide(callback: CallbackQuery) -> None:
    await callback.message.edit_text(f"{html_emoji('ok')} Скрыто.")
    await callback.answer()


@router.callback_query(F.data == "aqua_show:profile")
async def aqua_show_profile(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    try:
        await _render_profile_screen(callback)
    except Exception:
        import logging

        logging.getLogger(__name__).exception("aqua_show_profile failed tg=%s", callback.from_user.id)
        if callback.message:
            await callback.message.answer(
                f"{html_emoji('fail')} Не удалось открыть профиль. Попробуй ещё раз или /start.",
                parse_mode="HTML",
            )
    await callback.answer()


@router.callback_query(F.data == "aqua_show:key")
async def aqua_show_key(callback: CallbackQuery) -> None:
    await callback.answer()
    await _render_key_screen(callback)


@router.callback_query(F.data == "aqua_service_pick")
async def aqua_service_pick(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    async with Session() as session:
        user = await get_or_create_user(session, callback.from_user.id)
        service = await get_user_aqua_service(session, user)
    if not AQUA_SERVICE_CHOICES:
        text = (
            f"{html_emoji('compass')} <b>Сервис</b>\n\n"
            "Список сервисов пуст. На сервере задай "
            "<code>AQUA_SERVICES=code1,code2</code> и положи HTML в "
            "<code>data/HTML/&lt;code&gt;/</code>."
        )
        await callback.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[back_inline("aqua_show:profile")]]
            ),
            parse_mode="HTML",
        )
        await callback.answer()
        return
    text = (
        f"{html_emoji('compass')} <b>Сервис</b>\n\n"
        f"Текущий: <b>{aqua_service_label(service)}</b>\n\n"
        "Выберите сервис для генерации ссылок и HTML-шаблонов:"
    )
    await callback.message.edit_text(
        text,
        reply_markup=service_picker_kb(service),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "aqua_domain_pick")
async def aqua_domain_pick(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    async with Session() as session:
        user = await get_or_create_user(session, callback.from_user.id)
        mode = await get_user_gag_domain_mode(session, user)
    await callback.message.edit_text(
        _domain_menu_text(mode),
        reply_markup=_domain_mode_kb(mode),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("aqua_domain_set:"))
async def aqua_domain_set(callback: CallbackQuery, state: FSMContext) -> None:
    code = (callback.data or "").split(":", 1)[1].strip().lower()
    allowed = {"team", "1", "2", "3", "4"}
    if code not in allowed:
        return await callback.answer("Неизвестный домен", show_alert=True)
    async with Session() as session:
        user = await get_or_create_user(session, callback.from_user.id)
        await set_user_gag_domain_mode(session, user, code)
        await session.commit()
        mode = await get_user_gag_domain_mode(session, user)
    await state.clear()
    await callback.message.edit_text(
        _domain_menu_text(mode),
        reply_markup=_domain_mode_kb(mode),
        parse_mode="HTML",
    )
    await callback.answer(toast("ok", profile_domain_label(mode)))


@router.callback_query(F.data.startswith("aqua_service_set:"))
async def aqua_service_set(callback: CallbackQuery, state: FSMContext) -> None:
    code = (callback.data or "").split(":", 1)[1].strip()
    if code not in AQUA_SERVICE_CHOICES:
        return await callback.answer("Неизвестный сервис", show_alert=True)

    async with Session() as session:
        user = await get_or_create_user(session, callback.from_user.id)
        await set_user_setting(session, user, AQUA_SERVICE_KEY, code)
        await session.commit()

    await state.clear()
    await callback.answer(f"Сервис: {aqua_service_label(code)}")
    await _render_profile_screen(callback)


@router.callback_query(F.data == "aqua_profile_create")
async def aqua_profile_create(callback: CallbackQuery, state: FSMContext) -> None:
    async with Session() as session:
        user = await get_or_create_user(session, callback.from_user.id)
        cur_title = await get_user_profile_title(session, user) or "—"
        cur_buyer = await get_user_profile_buyer_name(session, user) or "—"
        cur_addr = await get_user_profile_address(session, user) or "—"

    await state.clear()
    await state.set_state(ProfileState.title)
    await callback.message.edit_text(
        f"{html_emoji('edit')} <b>Профиль</b>\n\n"
        f"Сейчас:\n"
        f"• Название: <code>{cur_title}</code>\n"
        f"• Имя получателя: <code>{cur_buyer}</code>\n"
        f"• Адрес: <code>{cur_addr}</code>\n\n"
        "Отправь <b>название профиля</b> одним сообщением.\n"
        "<i>Например: Anna</i>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[back_inline("aqua_show:profile", text="Отмена")]]
        ),
    )
    await callback.answer()


@router.message(ProfileState.title)
async def profile_title_step(message: Message, state: FSMContext) -> None:
    title = (message.text or "").strip()
    if not title:
        await message.answer(f"{html_emoji('fail')} Название пустое.")
        return
    await state.update_data(title=title)
    await state.set_state(ProfileState.buyer_name)
    await message.answer(
        "Отправь <b>имя получателя</b> — оно будет на сгенерированной ссылке.\n"
        "<i>Например: Anna Johansen</i>",
        parse_mode="HTML",
    )


@router.message(ProfileState.buyer_name)
async def profile_buyer_step(message: Message, state: FSMContext) -> None:
    buyer = (message.text or "").strip()
    if not buyer:
        await message.answer(f"{html_emoji('fail')} Имя пустое.")
        return
    await state.update_data(buyer_name=buyer)
    await state.set_state(ProfileState.address)
    await message.answer(
        "Отправь <b>адрес доставки</b> одним сообщением.\n"
        "<i>Например: Belgia 88 dom 33 ylica sosal</i>",
        parse_mode="HTML",
    )


@router.message(ProfileState.address)
async def profile_address_step(message: Message, state: FSMContext) -> None:
    addr = (message.text or "").strip()
    if not addr:
        await message.answer(f"{html_emoji('fail')} Адрес пустой.")
        return
    data = await state.get_data()
    title = (data.get("title") or "").strip()
    buyer = (data.get("buyer_name") or "").strip()

    async with Session() as session:
        user = await get_or_create_user(session, message.from_user.id)
        await set_user_setting(session, user, AQUA_PROFILE_TITLE_KEY, title)
        await set_user_setting(session, user, AQUA_PROFILE_NAME_KEY, buyer)
        await set_user_setting(session, user, AQUA_PROFILE_ADDRESS_KEY, addr)
        await session.commit()

    await state.clear()
    await message.answer(f"{html_emoji('ok')} Профиль сохранён.", reply_markup=profile_screen_kb())


@router.callback_query(F.data == "aqua_test_keys")
async def aqua_test_keys(callback: CallbackQuery) -> None:
    await callback.answer("Проверяю…")
    async with Session() as session:
        user = await get_or_create_user(session, callback.from_user.id)
        user_key = await get_user_aqua_user_key_async(session, user)
        if not user_key:
            return await callback.message.answer(
                f"{html_emoji('fail')} Личный ключ не задан. {menu_path(('settings', ''), ('key', 'Ключ'))}",
                parse_mode="HTML",
            )
        if not generate_api_configured():
            return await callback.message.answer(
                f"{html_emoji('fail')} На сервере не задан GENERATE_API_BASE / GAG_API_BASE."
            )
        try:
            await verify_gag_auth(user_api_key=user_key)
        except AquaError as e:
            return await callback.message.answer(
                f"{html_emoji('fail')} <b>API генерации</b>\n<code>{html.escape(str(e)[:400])}</code>",
                parse_mode="HTML",
            )
    await callback.message.answer(f"{html_emoji('ok')} Ключи работают (API генерации).", parse_mode="HTML")


@router.callback_query(F.data == "aqua_set:user_key")
async def aqua_set_user_key_begin(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(KeysState.waiting_value)
    try:
        await callback.message.edit_text(
            f"{html_emoji('write')} <b>Личный API-ключ</b>\n\n"
            "Отправь <b>apikey</b> из панели API <b>одним сообщением</b>.\n"
            "<i>Пример: d1f491dce948267abdf321c800ec6c73</i>\n\n"
            "Отмена: «Назад» в меню настроек.",
            reply_markup=_back_kb(),
            parse_mode="HTML",
        )
    except TelegramBadRequest:
        await callback.message.answer(
            f"{html_emoji('write')} <b>Личный API-ключ</b>\n\n"
            "Отправь <b>apikey</b> одним сообщением.",
            reply_markup=_back_kb(),
            parse_mode="HTML",
        )
    await callback.answer("Жду ключ…")


@router.message(KeysState.waiting_value)
async def keys_set_finish(message: Message, state: FSMContext) -> None:
    value = clean_secret((message.text or "").strip())
    if not value:
        await message.answer(f"{html_emoji('fail')} Пустое значение.")
        return

    async with Session() as session:
        user = await get_or_create_user(session, message.from_user.id)
        value = normalize_aqua_api_key(value)
        user.goo_user_api_key_aqua = value
        await set_user_setting(session, user, AQUA_USER_API_KEY_SETTING, value)
        await session.commit()

    await state.clear()
    await message.answer(
        f"{html_emoji('ok')} Ключ сохранён.\n"
        f"{menu_path(('settings', ''), ('key', 'Ключ'))} — «Проверить ключ».",
        parse_mode="HTML",
    )
