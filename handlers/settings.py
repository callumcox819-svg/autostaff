# handlers/settings.py
from __future__ import annotations

import asyncio
import html
import json
import logging
import re
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.exceptions import TelegramBadRequest

from database import Session, db_session
from services.users import get_or_create_user
from services.country_scope import (
    country_display_name,
    get_scoped_setting,
    set_scoped_setting,
)
from services.enabled_countries import get_active_country
from utils.callback_safe import callback_answer_safe
from utils.ui_emoji import html_emoji, inline_button, menu_path, msg_fail, msg_ok, msg_wait, msg_warn, toast


def _back_kb(callback_data: str = "settings_open") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[inline_button("back", "Назад", callback_data=callback_data)]]
    )

from services.aqua_keys import (
    AQUA_SERVICE_KEY,
    aqua_service_for_html_dir,
    aqua_service_label,
    get_user_aqua_service,
    is_valid_aqua_service,
)
from config import config

class SpoofNameState(StatesGroup):
    waiting_name = State()

router = Router()

# =========================
# Утилиты
# =========================

async def _safe_send(target, *args, **kwargs):
    """Safely await a coroutine OR call an async function with args/kwargs."""
    try:
        coro = target(*args, **kwargs) if callable(target) else target
        return await coro
    except TelegramBadRequest:
        return None
    except Exception:
        logger.exception("_safe_send")
        return None


async def _cq_edit_text(
    callback: CallbackQuery,
    text: str,
    *,
    reply_markup: InlineKeyboardMarkup | None = None,
    parse_mode: str = "HTML",
) -> None:
    """Правка inline-меню: через bot.edit_message_text (не message.edit_text через _safe_send)."""
    msg = callback.message
    if msg is None:
        return
    try:
        await callback.bot.edit_message_text(
            text,
            chat_id=msg.chat.id,
            message_id=msg.message_id,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
        )
    except TelegramBadRequest:
        pass


logger = logging.getLogger(__name__)

SETTINGS_MENU_TEXT = "Настройки"


def _settings_title_html(country_name: str = "") -> str:
    title = f"{html_emoji('settings')} <b>Настройки</b>"
    if country_name:
        return f"{title}\nРабочая страна: <b>{html.escape(country_name)}</b>"
    return title


async def _settings_title_for_user(tg_user_id: int) -> str:
    try:
        async with db_session() as session:
            user = await get_or_create_user(session, int(tg_user_id))
            cc = await get_active_country(session, user)
        return _settings_title_html(country_display_name(cc))
    except Exception:
        return _settings_title_html()


def match_settings_menu_text(text: str | None) -> bool:
    """Кнопка «⚙️ Настройки» с главной клавиатуры (устойчиво к вариантам emoji)."""
    t = (text or "").strip().casefold().replace("\ufe0f", "")
    if not t:
        return False
    if "настройки" in t:
        return True
    return t in {"settings", "setting", "⚙️ настройки"}


async def open_settings_menu(message: Message, state: FSMContext) -> None:
    await state.clear()
    tg_id = int(message.from_user.id)
    logger.info("open_settings_menu tg=%s text=%r", tg_id, message.text)
    try:
        kb = await asyncio.wait_for(
            _settings_menu_kb_for_user(tg_id),
            timeout=float(__import__("os").getenv("SETTINGS_MENU_DB_TIMEOUT_SEC", "12")),
        )
        await message.answer(
            await _settings_title_for_user(tg_id),
            reply_markup=kb,
            parse_mode="HTML",
        )
    except asyncio.TimeoutError:
        logger.error("open_settings_menu DB timeout tg=%s", tg_id)
        await message.answer(_settings_title_html(), reply_markup=settings_menu_kb({}), parse_mode="HTML")
    except Exception:
        logger.exception("open_settings_menu failed tg=%s", tg_id)
        await message.answer("не открылось, /start")


# =========================
# HTML Nick
# =========================

SUBJECT_TEMPLATE_KEY = "subject_template"
HTML_THEME_KEY = "html_theme"
FAST_MAILING_KEY = "fast_mailing"

HTMLNICK_KEY = "html_nick"
COUNTRY_KEY = "country"
TEAM_KEY = "team"

async def load_html_nick(session: Session, tg_user_id: int) -> str | None:
    user = await get_or_create_user(session, tg_user_id)
    val = await get_scoped_setting(session, user, HTMLNICK_KEY)
    return (val or "").strip() or None

async def save_html_nick(session: Session, tg_user_id: int, value: str | None) -> None:
    user = await get_or_create_user(session, tg_user_id)
    v = (value or "").strip() or None
    await set_scoped_setting(session, user, HTMLNICK_KEY, v)


# =========================
# FSM for simple inputs (nick, priority, html theme)
# =========================


class _SettingsInput(StatesGroup):
    html_nick = State()
    subject_template = State()
    priority = State()
    html_theme = State()
    sender_name = State()


def settings_menu_kb(flags: dict[str, bool]) -> InlineKeyboardMarkup:
    from utils.ui_emoji import inline_button, toggle_button

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                inline_button("status", "Приоритет\nотправки", callback_data="priority_menu"),
                inline_button("presets", "Пресеты", callback_data="presets_menu"),
            ],
            [
                inline_button("presets", "Темы писем", callback_data="mail_subjects"),
            ],
            [
                toggle_button(flags.get("smart_mode", False), "Умный режим", "ref_toggle:smart_mode"),
                inline_button("presets", "Умные пресеты", callback_data="smart_presets_menu"),
            ],
            [
                toggle_button(flags.get("spoofing", False), "Спуфинг", "ref_toggle:spoofing"),
                inline_button("profile", "Имя для\nспуфинга", callback_data="spoof_name_menu"),
            ],
            [
                inline_button("write", "Имя\nотправителя", callback_data="sender_name_menu"),
            ],
            [
                toggle_button(
                    flags.get("block_control", False),
                    "Контроль\nблокировок",
                    "ref_toggle:block_control",
                ),
            ],
            [
                inline_button("email", "E-mail", callback_data="settings_accounts"),
                inline_button("proxy", "Прокси", callback_data="settings_proxies"),
            ],
            [
                inline_button("key", "Команды API", callback_data="api_teams"),
                inline_button("compass", "Страны", callback_data="countries_menu"),
            ],
            [
                inline_button("hide", "Скрыть", callback_data="ref_hide"),
            ],
        ]
    )


async def _settings_menu_kb_for_user(tg_user_id: int) -> InlineKeyboardMarkup:
    async with db_session() as session:
        user = await get_or_create_user(session, tg_user_id)

        async def _b_scoped(key: str, default: bool = False) -> bool:
            v = await get_scoped_setting(session, user, key)
            if v is None:
                return default
            s = str(v).strip().lower()
            return s in {"1", "true", "yes", "on", "y"}

        flags = {
            "smart_mode": await _b_scoped("smart_mode", False),
            "spoofing": await _b_scoped("spoofing", False),
            "block_control": await _b_scoped("block_control", False),
        }

    return settings_menu_kb(flags)


def _is_settings_menu_message(message: Message) -> bool:
    return match_settings_menu_text(message.text)


@router.message(F.func(_is_settings_menu_message))
async def settings_open(message: Message, state: FSMContext) -> None:
    await open_settings_menu(message, state)


async def _spoof_name_menu_payload(tg_user_id: int) -> tuple[str, InlineKeyboardMarkup] | None:
    """Текст и клавиатура меню HTML-имени. None — сервис не выбран."""
    async with db_session() as session:
        user = await get_or_create_user(session, tg_user_id)
        from services.aqua_keys import resolve_html_service

        service = await resolve_html_service(session, user)
        if not is_valid_aqua_service(service):
            from services.aqua_keys import html_dir_for_service

            if not html_dir_for_service(service):
                return None
        key = _html_nick_key_for_service(service)
        cur = (await get_scoped_setting(session, user, key) or "").strip()

    label = _service_label(service)
    cur_disp = html.escape(cur) if cur else "— не задано —"
    text = (
        f"{html_emoji('user')} <b>HTML: спуфинг</b>\n"
        f"Сервис: <b>{html.escape(label)}</b>\n\n"
        f"При {html_emoji('green')} <b>Спуфинг</b> и отправке <b>HTML</b>:\n"
        f"{html_emoji('user')} <b>Имя (From):</b> <code>{cur_disp}</code>\n"
        f"Тема письма — всегда <code>Re:</code> исходного диалога "
        f"(иначе Gmail открывает второе письмо).\n\n"
        f"Текстом / пресет / рассылка — имя из «{html_emoji('email')} E-mail»."
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [inline_button("check", f"Установить имя ({label})", callback_data="spoof_name_set")],
            _back_kb("settings_open").inline_keyboard[0],
        ]
    )
    return text, kb


async def _show_spoof_name_menu_message(message: Message, *, prompt_chat_id: int | None, prompt_msg_id: int | None) -> None:
    payload = await _spoof_name_menu_payload(message.from_user.id)
    if not payload:
        await message.answer(
            f"Сначала заполните профиль: {menu_path(('settings', ''), ('profile', 'Профиль'))}.",
            parse_mode="HTML",
        )
        return
    text, kb = payload
    if prompt_chat_id and prompt_msg_id:
        try:
            await message.bot.edit_message_text(
                text,
                chat_id=prompt_chat_id,
                message_id=prompt_msg_id,
                reply_markup=kb,
                parse_mode="HTML",
            )
            return
        except TelegramBadRequest:
            pass
    await message.answer(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data == "spoof_name_menu")
async def spoof_name_menu(callback: CallbackQuery, state: FSMContext) -> None:
    """Меню установки имени (смены ника) для HTML, привязанное к выбранному сервису профиля."""
    await state.clear()
    payload = await _spoof_name_menu_payload(callback.from_user.id)
    if not payload:
        return await callback.answer(
            "Нет HTML-шаблона для выбранной страны/площадки.",
            show_alert=True,
        )
    text, kb = payload
    await _cq_edit_text(callback, text, reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data == "spoof_name_set")
async def spoof_name_set(callback: CallbackQuery, state: FSMContext) -> None:
    async with Session() as session:
        user = await get_or_create_user(session, callback.from_user.id)
        from services.aqua_keys import resolve_html_service

        service = await resolve_html_service(session, user)
        if not is_valid_aqua_service(service):
            from services.aqua_keys import html_dir_for_service

            if not html_dir_for_service(service):
                return await callback.answer(
                    "Нет HTML-шаблона для выбранной страны/площадки (DE: Kleinanzeigen).",
                    show_alert=True,
                )
    await state.set_state(SpoofNameState.waiting_name)
    await state.update_data(
        service=service,
        spoof_prompt_chat_id=callback.message.chat.id if callback.message else None,
        spoof_prompt_msg_id=callback.message.message_id if callback.message else None,
    )
    await _cq_edit_text(
        callback,
        "Введите имя для спуфинга (смены ника) для HTML:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[inline_button("cancel", "Отмена", callback_data="spoof_name_menu")]]
        ),
    )
    await callback.answer()


@router.message(SpoofNameState.waiting_name)
async def spoof_name_save(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    service = (data.get("service") or "").strip()
    name = (message.text or "").strip()
    if not name:
        return await message.answer("Введите имя текстом.")
    async with db_session() as session:
        user = await get_or_create_user(session, message.from_user.id)
        key = _html_nick_key_for_service(service)
        await set_scoped_setting(session, user, key, name)

    prompt_chat_id = data.get("spoof_prompt_chat_id")
    prompt_msg_id = data.get("spoof_prompt_msg_id")
    await state.clear()

    await message.answer(msg_ok("Имя добавлено"), parse_mode="HTML")
    await _show_spoof_name_menu_message(
        message,
        prompt_chat_id=int(prompt_chat_id) if prompt_chat_id else None,
        prompt_msg_id=int(prompt_msg_id) if prompt_msg_id else None,
    )


@router.callback_query(F.data == "settings_open")
async def settings_open_cb(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback_answer_safe(callback)
    try:
        kb = await asyncio.wait_for(
            _settings_menu_kb_for_user(callback.from_user.id),
            timeout=float(__import__("os").getenv("SETTINGS_MENU_DB_TIMEOUT_SEC", "12")),
        )
    except asyncio.TimeoutError:
        logger.error("settings_open_cb DB timeout tg=%s", callback.from_user.id)
        kb = settings_menu_kb({})
    except Exception:
        logger.exception("settings_open_cb failed tg=%s", callback.from_user.id)
        kb = settings_menu_kb({})
    await _cq_edit_text(callback, await _settings_title_for_user(callback.from_user.id), reply_markup=kb, parse_mode="HTML")


# =========================
# Callbacks настроек (темы, тайминги, HTML nick)
# =========================


@router.callback_query(F.data == "sender_name_menu")
async def sender_name_menu(callback: CallbackQuery) -> None:
    """Show current sender name and provide existing 'sender_name_set' action."""
    async with Session() as session:
        user = await get_or_create_user(session, callback.from_user.id)
        current = (getattr(user, "sender_name", None) or "—").strip() or "—"

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [inline_button("edit", "Установить", callback_data="sender_name_set")],
            _back_kb("settings_open").inline_keyboard[0],
        ]
    )
    await callback.message.edit_text(
        f"{html_emoji('write')} <b>Имя отправителя</b>\n\n"
        f"Текущее имя: <code>{html.escape(current)}</code>\n\n"
        "Это From для рассылки, тест-маила и обычных ответов "
        "(не HTML-спуф).\n"
        "Нажми «Установить», чтобы задать другое.",
        reply_markup=kb,
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "sender_name_set")
async def sender_name_set_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(_SettingsInput.sender_name)
    await callback.message.edit_text(
        f"{html_emoji('write')} <b>Имя отправителя</b>\n\n"
        "Отправь имя и фамилию одним сообщением "
        "(например: <code>Maria Johansen</code>).\n"
        "«-» — очистить.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=_back_kb("sender_name_menu").inline_keyboard,
        ),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(_SettingsInput.sender_name)
async def sender_name_set_save(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    if not raw:
        await message.answer(msg_fail("Пустое значение. Отправь ещё раз."), parse_mode="HTML")
        return
    if raw == "-":
        value = ""
    else:
        words = [w for w in raw.split() if w.strip()]
        if len(words) < 2:
            await message.answer(
                "Укажи имя и фамилию через пробел (минимум 2 слова).\n"
                "Пример: <code>Maria Johansen</code>",
                parse_mode="HTML",
            )
            return
        value = raw
    async with Session() as session:
        user = await get_or_create_user(session, message.from_user.id)
        from services.sender_identity import record_sender_name_change

        await record_sender_name_change(session, user, value)
        user.sender_name = value or None
        await session.commit()
        session.expire(user, ["sender_name"])
    await state.clear()
    shown = html.escape(value) if value else "—"
    await message.answer(
        f"{msg_ok('Имя отправителя сохранено.')}\n<code>{shown}</code>",
        parse_mode="HTML",
    )


@router.callback_query(F.data == "settings_templates")
async def settings_templates(callback: CallbackQuery, state: FSMContext) -> None:
    """Open presets list (same UI as умные пресеты)."""
    from handlers.templates import presets_menu

    await presets_menu(callback, state)


@router.callback_query(F.data == "html_nick_menu")
async def html_nick_menu(callback: CallbackQuery, state: FSMContext) -> None:
    async with Session() as session:
        cur = await load_html_nick(session, callback.from_user.id)

    await state.clear()

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [inline_button("edit", "Установить", callback_data="html_nick_set")],
            _back_kb("settings_open").inline_keyboard[0],
        ]
    )

    await callback.message.edit_text(
        f"{html_emoji('write')} <b>Смена ника</b>\n\n"
        f"Текущий ник: <code>{cur or '—'}</code>\n\n"
        "Нажми «Установить», чтобы задать другой.",
        reply_markup=kb,
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "html_nick_set")
async def html_nick_set_start(callback: CallbackQuery, state: FSMContext) -> None:
    """Ask user to send a new nick (HTML nick) after pressing 'Установить'."""
    await state.clear()
    await state.set_state(_SettingsInput.html_nick)

    await callback.message.edit_text(
        f"{html_emoji('write')} <b>Смена ника</b>\n\n"
        "Отправь новый ник одним сообщением (или «-», чтобы очистить).",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=_back_kb("settings_open").inline_keyboard,
        ),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(_SettingsInput.html_nick)
async def html_nick_set(message: Message, state: FSMContext) -> None:
    value = (message.text or "").strip()
    if not value:
        await message.answer(msg_fail("Пустое значение. Отправь ещё раз."), parse_mode="HTML")
        return
    if value == "-":
        value = ""
    async with Session() as session:
        await save_html_nick(session, message.from_user.id, value)
    await state.clear()
    await message.answer(msg_ok("Сохранено."), parse_mode="HTML")


@router.callback_query(F.data == "settings_back")
async def settings_back(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    try:
        await callback.message.edit_text(
            await _settings_title_for_user(callback.from_user.id),
            reply_markup=await _settings_menu_kb_for_user(callback.from_user.id),
            parse_mode="HTML",
        )
    except Exception:
        pass
    await callback.answer()


def _service_label(code: str) -> str:
    return aqua_service_label(code)


def _html_nick_key_for_service(service: str) -> str:
    sub = aqua_service_for_html_dir((service or "").strip() or None)
    return f"html_nick_{sub}" if sub else HTMLNICK_KEY


# =========================
# Reference menu toggles / stubs (1v1 UI)
# =========================

_REF_TOGGLE_KEYS = {
    "check_send": "check_send",
    "subj_insert": "subj_insert",
    "smart_mode": "smart_mode",
    "spoofing": "spoofing",
    "html_mailer": "html_mailer",
    "saver": "saver",
    "card": "card",
    "block_control": "block_control",
    "fast_mailing": "fast_mailing",
}


def _simple_back_kb() -> InlineKeyboardMarkup:
    return _back_kb("settings_open")


@router.callback_query(F.data.startswith("ref_toggle:"))
async def ref_toggle(callback: CallbackQuery):
    key = (callback.data or "").split(":", 1)[1].strip()
    db_key = _REF_TOGGLE_KEYS.get(key)
    if not db_key:
        return await callback.answer()

    async with db_session() as session:
        user = await get_or_create_user(session, callback.from_user.id)
        cur = await get_scoped_setting(session, user, db_key)
        cur_s = str(cur or "").strip().lower()
        cur_b = cur_s in {"1", "true", "yes", "on", "y"}
        new_b = not cur_b
        await set_scoped_setting(session, user, db_key, "1" if new_b else "0")

    kb = await _settings_menu_kb_for_user(callback.from_user.id)
    await _cq_edit_text(
        callback,
        await _settings_title_for_user(callback.from_user.id),
        reply_markup=kb,
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "ref_hide")
async def ref_hide(callback: CallbackQuery):
    # Try delete message, else just remove buttons
    try:
        await callback.message.delete()
    except Exception:
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
    await callback.answer()


@router.callback_query(F.data.startswith("ref_open:"))
async def ref_open(callback: CallbackQuery, state: FSMContext):
    """Helper screens for reference menu items that are not full modules in this repo."""
    screen = (callback.data or "").split(":", 1)[1].strip()
    if screen == "commands":
        await state.clear()
        msg = (
            f"{html_emoji('write')} <b>Команды</b>\n\n"
            "Режим: <b>burst</b> (ротация ящиков и текстов)\n\n"
            "/send — запустить рассылку\n"
            "/stop — остановить рассылку\n"
            "/reset — очистить очередь (лиды в БД остаются)\n"
            "/stat — статус рассылки"
        )
        await callback.message.edit_text(
            msg,
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=_back_kb("settings_open").inline_keyboard,
            ),
            parse_mode="HTML",
        )
        await callback.answer()
        return
    if screen in {"themes", "themes_html"}:
        await state.clear()
        title = (
            f"{html_emoji('pin')} <b>Темы</b>"
            if screen == "themes"
            else f"{html_emoji('profile')} <b>Тема для HTML</b>"
        )
        text = (
            f"{title}\n\n"
            f"В этом проекте темы/шаблоны управляются через «{html_emoji('profile')} Пресеты».\n"
            "Если нужно — добавлю отдельный менеджер тем 1в1 (лист/добавить/удалить/выбрать)."
        )
        await callback.message.edit_text(text, reply_markup=_simple_back_kb(), parse_mode="HTML")
        await callback.answer()
        return

    if screen == "smart_presets":
        await callback.answer()
        from handlers.templates import smart_presets_menu

        await smart_presets_menu(callback, state)
        return

    if screen in {"cases", "scenario_name", "rotation"}:
        await state.clear()
        labels = {
            "cases": f"{html_emoji('green')} <b>Сценарии</b>",
            "scenario_name": f"{html_emoji('profile')} <b>Имя для сценариев</b>",
            "rotation": f"{html_emoji('refresh')} <b>Ротация</b>",
        }
        text = (
            f"{labels.get(screen, html_emoji('info'))}\n\n"
            "Этот раздел в твоём проекте пока не был реализован как отдельный экран.\n"
            "Если хочешь 1в1 — напиши, какие именно действия там должны быть (по видео), и я добавлю."
        )
        await callback.message.edit_text(text, reply_markup=_simple_back_kb(), parse_mode="HTML")
        await callback.answer()
        return

    # unknown
    await callback.answer("OK")


# =========================
# Команды (как на видео) — просто экран с командами + Назад
# =========================

@router.callback_query(F.data == "ref_open:commands")
async def ref_open_commands(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    text = (
        f"{html_emoji('write')} <b>Команды</b>\n\n"
        "/send — запустить рассылку\n"
        "/stop — остановить рассылку\n"
        "/reset — очистить очередь (лиды в БД остаются)\n"
        "/stat — статус рассылки\n\n"
        "Также: просто пришли JSON/TXT с объявлениями — бот провалидирует и сохранит в БД."
    )
    await _safe_send(callback.message.edit_text(
        text,
        reply_markup=_back_kb("settings_open"),
        parse_mode="HTML",
    ))
    await callback.answer()

# =========================
# Темы писем → handlers.mail_subjects
# =========================

@router.callback_query(F.data.startswith("themes_preset:"))
async def themes_legacy_preset(callback: CallbackQuery, state: FSMContext) -> None:
    from handlers.mail_subjects import mail_subjects_open

    await mail_subjects_open(callback, state)


@router.callback_query(F.data.in_({"themes_edit", "themes_clear"}))
async def themes_legacy_redirect(callback: CallbackQuery, state: FSMContext) -> None:
    from handlers.mail_subjects import mail_subjects_open

    await mail_subjects_open(callback, state)


@router.message(_SettingsInput.subject_template)
async def themes_set(message: Message, state: FSMContext):
    await state.clear()
    from handlers.mail_subjects import build_mail_subjects_view

    text, kb = await build_mail_subjects_view(message.from_user.id, 0)
    await message.answer(
        f"{html_emoji('info')} Список тем — в меню «Темы писем».\n\n{text}",
        reply_markup=kb,
        parse_mode="HTML",
    )

# =========================
# Тема для HTML (реально сохраняем html_theme)
# =========================

@router.callback_query(F.data == "html_theme_menu")
async def html_theme_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    async with Session() as session:
        user = await get_or_create_user(session, callback.from_user.id)
        cur = (await get_scoped_setting(session, user, HTML_THEME_KEY) or "").strip()

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [inline_button("edit", "Изменить", callback_data="html_theme_edit")],
        [inline_button("delete", "Очистить", callback_data="html_theme_clear")],
        _back_kb("spoof_name_menu").inline_keyboard[0],
    ])
    cur_show = cur if cur else "—"
    txt = (
        f"{html_emoji('pin')} <b>Тема для HTML</b>\n\n"
        "Больше не подставляется в Subject письма — из‑за неё Gmail "
        "открывал HTML отдельно от диалога.\n"
        "Спуфинг HTML: только <b>имя From</b> и <code>{{NICK}}</code>; "
        "тема всегда <code>Re:</code> исходного треда.\n\n"
        f"Старое значение (не используется):\n<code>{cur_show}</code>"
    )
    await _safe_send(callback.message.edit_text(txt, reply_markup=kb, parse_mode="HTML"))
    await callback.answer()

@router.callback_query(F.data == "html_theme_edit")
async def html_theme_edit(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.set_state(_SettingsInput.html_theme)
    await _safe_send(callback.message.edit_text(
        f"{html_emoji('profile')} <b>Тема для HTML</b>\n\nОтправь тему одной строкой.\n"
        "Чтобы удалить — отправь <code>-</code>.",
        reply_markup=_back_kb("spoof_name_menu"),
        parse_mode="HTML",
    ))
    await callback.answer()

@router.message(_SettingsInput.html_theme)
async def html_theme_set(message: Message, state: FSMContext):
    val = (message.text or "").strip()
    if val == "-":
        val = ""
    async with Session() as session:
        user = await get_or_create_user(session, message.from_user.id)
        await set_scoped_setting(session, user, HTML_THEME_KEY, val)
    await state.clear()
    await message.answer(
        f"{msg_ok('Тема для HTML сохранена.')}\nПример: <code>Your item sold</code>",
        reply_markup=await _settings_menu_kb_for_user(message.from_user.id),
    )

@router.callback_query(F.data == "html_theme_clear")
async def html_theme_clear(callback: CallbackQuery, state: FSMContext):
    async with Session() as session:
        user = await get_or_create_user(session, callback.from_user.id)
        await set_scoped_setting(session, user, HTML_THEME_KEY, "")
    await callback.answer(toast("ok", "Очищено"))
    await html_theme_menu(callback, state)

# =========================
# Приоритет доменов — сохраняем список доменов по порядку
# =========================

DOMAIN_PRIORITY_KEY = "domain_priority"

@router.callback_query(F.data == "priority_menu")
async def priority_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    async with db_session() as session:
        user = await get_or_create_user(session, callback.from_user.id)
        raw = await get_scoped_setting(session, user, DOMAIN_PRIORITY_KEY)
        cc_name = country_display_name(await get_active_country(session, user))
        try:
            items = json.loads(raw) if raw else []
        except Exception:
            items = []
    if not isinstance(items, list):
        items = []

    if items:
        lst = "\n".join([f"{i+1}. <code>{d}</code>" for i, d in enumerate(items)])
    else:
        lst = "—"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [inline_button("edit", "Изменить приоритет", callback_data="priority_edit")],
        [inline_button("delete", "Сбросить приоритет", callback_data="priority_reset")],
        _back_kb("settings_open").inline_keyboard[0],
    ])
    await _safe_send(callback.message.edit_text(
        f"{html_emoji('status')} <b>Приоритет отправки</b>\n"
        f"Страна: <b>{html.escape(cc_name)}</b>\n\n"
        "Домен №1 валидируется первым, потом №2 и т.д.\n"
        "Список свой для каждой рабочей страны.\n\n"
        f"<b>Текущий приоритет:</b>\n{lst}",
        reply_markup=kb,
        parse_mode="HTML",
    ))

@router.callback_query(F.data == "priority_edit")
async def priority_edit(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.set_state(_SettingsInput.priority)
    await _safe_send(callback.message.edit_text(
        f"{html_emoji('status')} <b>Приоритет отправки</b>\n\n"
        "Отправь домены списком (каждый с новой строки).\n"
        "Пример:\n<code>gmx.de\ngmail.com\n...</code>\n\n"
        "Чтобы очистить — отправь <code>-</code>",
        reply_markup=_back_kb("priority_menu"),
        parse_mode="HTML",
    ))
    await callback.answer()

@router.message(_SettingsInput.priority)
async def priority_set(message: Message, state: FSMContext):
    txt = (message.text or "").strip()
    if txt == "-":
        items = []
    else:
        items = [re.sub(r"^https?://", "", x.strip().lower()) for x in txt.splitlines() if x.strip()]
    async with Session() as session:
        user = await get_or_create_user(session, message.from_user.id)
        await set_scoped_setting(session, user, DOMAIN_PRIORITY_KEY, json.dumps(items))
    await state.clear()
    await message.answer(msg_ok("Сохранено."), reply_markup=await _settings_menu_kb_for_user(message.from_user.id), parse_mode="HTML")

@router.callback_query(F.data == "priority_reset")
async def priority_reset(callback: CallbackQuery, state: FSMContext):
    async with Session() as session:
        user = await get_or_create_user(session, callback.from_user.id)
        await set_scoped_setting(session, user, DOMAIN_PRIORITY_KEY, json.dumps([]))
    await callback.answer(toast("ok", "Сброшено"))
    await priority_menu(callback, state)

# =========================
# Ловим любые старые "назад" из старого меню, чтобы оно больше не всплывало
# =========================

@router.callback_query(F.data.in_({"settings_menu", "goo:settings", "goo_settings", "settings_main"}))
async def _force_settings_menu(callback: CallbackQuery, state: FSMContext):
    await settings_open_cb(callback, state)
