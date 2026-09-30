"""Настройки → Авто-парс: XProject API → валидация JSON."""

from __future__ import annotations

import asyncio
import html
import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from database import Session
from services.autoparse import (
    default_platform_for_country,
    get_autoparse_country,
    get_autoparse_key,
    get_autoparse_platform,
    get_json_count,
    get_saved_filters,
    listing_to_item,
    pick_existing_task,
    pick_task_for_filters,
    platform_schema,
    resolve_local_start_filters,
    schema_category_values,
    set_autoparse_country,
    set_autoparse_key,
    set_json_count,
    set_saved_filters,
    summarize_filters,
    supported_filter_keys,
    toggle_category_list,
    category_label,
)
from services.enabled_countries import countries_for_settings_ui
from services.users import get_or_create_user
from services.xproject_parser import (
    XProjectError,
    fetch_listings,
    fetch_schema,
    list_tasks,
    start_task,
    stop_task,
)
from utils.bg_jobs import cancel as bg_cancel
from utils.bg_jobs import is_running as bg_is_running
from utils.bg_jobs import start as bg_start
from utils.callback_safe import callback_answer_safe
from utils.ui_emoji import (
    back_inline,
    html_emoji,
    inline_button,
    menu_path,
    msg_fail,
    msg_ok,
    msg_wait,
    toast,
    toggle_button,
)

router = Router(name="autoparse")
logger = logging.getLogger(__name__)


class AutoparseState(StatesGroup):
    waiting_key = State()
    waiting_count = State()
    waiting_price_min = State()
    waiting_price_max = State()
    waiting_stop_words = State()
    waiting_num = State()
    waiting_period = State()
    waiting_reg = State()


def _mask_key(key: str) -> str:
    s = (key or "").strip()
    if len(s) <= 8:
        return "•" * max(len(s), 1) if s else "не задан"
    return f"{s[:4]}…{s[-4:]}"


async def _edit(callback: CallbackQuery, text: str, kb: InlineKeyboardMarkup) -> None:
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except TelegramBadRequest:
        try:
            await callback.message.answer(text, reply_markup=kb, parse_mode="HTML")
        except Exception:
            pass


def _menu_kb(*, running: bool) -> InlineKeyboardMarkup:
    rows = [
        [inline_button("key", "Ключ парсера", callback_data="autoparse_key")],
        [inline_button("compass", "Страна парсера", callback_data="autoparse_country")],
        [inline_button("presets", "Количество объяв. для JSON", callback_data="autoparse_count")],
        [inline_button("wrench", "Фильтры", callback_data="autoparse_filters")],
    ]
    if running:
        rows.append([inline_button("stop", "Стоп авто-парс", callback_data="autoparse_stop")])
    else:
        rows.append([inline_button("send", "Запуск", callback_data="autoparse_start")])
    rows.append([back_inline("settings_open")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _batches_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                inline_button("burst", "1 батч", callback_data="autoparse_run:1"),
                inline_button("burst", "5 батчей", callback_data="autoparse_run:5"),
            ],
            [
                inline_button("burst", "10 батчей", callback_data="autoparse_run:10"),
                inline_button("refresh", "∞ (0)", callback_data="autoparse_run:0"),
            ],
            [back_inline("autoparse")],
        ]
    )


async def _menu_text(session, user, *, running: bool) -> str:
    from services.country_scope import country_display_name as cname

    key = await get_autoparse_key(session, user)
    cc = await get_autoparse_country(session, user)
    plat = await get_autoparse_platform(session, user)
    n = await get_json_count(session, user)
    saved = await get_saved_filters(session, user, plat)
    run = "идёт" if running else "стоп"
    return (
        f"{html_emoji('search')} <b>Авто-парс</b>\n"
        f"{menu_path(('settings', 'Настройки'), ('search', 'Авто-парс'))}\n\n"
        f"<b>Ключ:</b> <code>{html.escape(_mask_key(key))}</code>\n"
        f"<b>Страна:</b> <b>{html.escape(cname(cc))}</b> · площадка <code>{html.escape(plat)}</code>\n"
        f"<b>Объявлений в JSON:</b> <code>{n}</code>\n"
        f"<b>Фильтры:</b> {html.escape(summarize_filters(saved))}\n"
        f"<b>Статус:</b> {html.escape(run)}\n\n"
        "Старт сам поднимает задачу XProject через API. "
        "Если в парсере уже есть задача этой площадки — её фильтры копируются и сохраняются. "
        "Иначе берутся сохранённые в «Фильтры». "
        "У XProject нет API на «общие фильтры» бота — только живые задачи.\n"
        "Запуск: 1 / 5 / 10 батчей или 0 — пока не остановишь / 402."
    )


@router.callback_query(F.data == "autoparse")
async def autoparse_open(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    async with Session() as session:
        user = await get_or_create_user(session, callback.from_user.id)
        running = bg_is_running(callback.from_user.id, "autoparse")
        text = await _menu_text(session, user, running=running)
    await _edit(callback, text, _menu_kb(running=running))
    await callback_answer_safe(callback)


@router.callback_query(F.data == "autoparse_key")
async def autoparse_key(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AutoparseState.waiting_key)
    await _edit(
        callback,
        f"{html_emoji('key')} <b>Ключ парсера</b>\n\n"
        "Пришли ключ XProject одним сообщением "
        "(<code>xp-live-…</code>). Заголовок <code>X-API-Key</code>.",
        InlineKeyboardMarkup(inline_keyboard=[[back_inline("autoparse")]]),
    )
    await callback_answer_safe(callback)


@router.message(AutoparseState.waiting_key)
async def autoparse_key_save(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    if not raw or raw.startswith("/"):
        await message.answer(msg_fail("Пришли ключ текстом."))
        return
    async with Session() as session:
        user = await get_or_create_user(session, message.from_user.id)
        await set_autoparse_key(session, user, raw)
        await session.commit()
        try:
            await fetch_schema(await get_autoparse_key(session, user))
            check = msg_ok("Ключ принят, схема парсера доступна.")
        except XProjectError as e:
            check = msg_fail(str(e))
    await state.clear()
    running = bg_is_running(message.from_user.id, "autoparse")
    async with Session() as session:
        user = await get_or_create_user(session, message.from_user.id)
        text = await _menu_text(session, user, running=running)
    await message.answer(check, parse_mode="HTML")
    await message.answer(text, reply_markup=_menu_kb(running=running), parse_mode="HTML")


@router.callback_query(F.data == "autoparse_country")
async def autoparse_country(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    async with Session() as session:
        user = await get_or_create_user(session, callback.from_user.id)
        cur = await get_autoparse_country(session, user)
    rows = []
    row = []
    for cid, label, emoji_key in countries_for_settings_ui():
        btn = (
            toggle_button(True, label, f"autoparse_cc:{cid}")
            if cid == cur
            else inline_button(emoji_key, label, callback_data=f"autoparse_cc:{cid}")
        )
        row.append(btn)
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([back_inline("autoparse")])
    await _edit(
        callback,
        f"{html_emoji('compass')} <b>Страна парсера</b>\n\n"
        f"Сейчас: <b>{html.escape(cur.upper())}</b> → "
        f"<code>{html.escape(default_platform_for_country(cur))}</code>.",
        InlineKeyboardMarkup(inline_keyboard=rows),
    )
    await callback_answer_safe(callback)


@router.callback_query(F.data.startswith("autoparse_cc:"))
async def autoparse_cc_set(callback: CallbackQuery, state: FSMContext) -> None:
    cc = (callback.data or "").split(":", 1)[-1].strip().lower()
    async with Session() as session:
        user = await get_or_create_user(session, callback.from_user.id)
        try:
            await set_autoparse_country(session, user, cc)
            await session.commit()
        except ValueError:
            await callback_answer_safe(callback, toast("fail", "Нет такой страны"), show_alert=True)
            return
        running = bg_is_running(callback.from_user.id, "autoparse")
        text = await _menu_text(session, user, running=running)
    await _edit(callback, text, _menu_kb(running=running))
    await callback_answer_safe(callback, toast("ok", cc.upper()))


@router.callback_query(F.data == "autoparse_count")
async def autoparse_count(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AutoparseState.waiting_count)
    async with Session() as session:
        user = await get_or_create_user(session, callback.from_user.id)
        n = await get_json_count(session, user)
    await _edit(
        callback,
        f"{html_emoji('presets')} <b>Количество объявлений в JSON</b>\n\n"
        f"Сейчас: <code>{n}</code>\n"
        "Пришли число от 10 до 500 — столько лотов в одном батче уйдёт в валидацию.",
        InlineKeyboardMarkup(inline_keyboard=[[back_inline("autoparse")]]),
    )
    await callback_answer_safe(callback)


@router.message(AutoparseState.waiting_count)
async def autoparse_count_save(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    async with Session() as session:
        user = await get_or_create_user(session, message.from_user.id)
        n = await set_json_count(session, user, raw)
        await session.commit()
        running = bg_is_running(message.from_user.id, "autoparse")
        text = await _menu_text(session, user, running=running)
    await state.clear()
    await message.answer(msg_ok(f"В JSON будет {n} объявлений."), parse_mode="HTML")
    await message.answer(text, reply_markup=_menu_kb(running=running), parse_mode="HTML")


_NONE = "Без фильтра"
_CATS_PAGE = 20
_DATE_OPTS = (
    ("fresh", "Свежие объявления"),
    ("1h", "1 час назад"),
    ("3h", "3 часа назад"),
    ("6h", "6 часов назад"),
    ("12h", "12 часов назад"),
    ("1d", "1 день назад"),
    ("3d", "3 дня назад"),
    ("7d", "1 неделя назад"),
)
_REG_OPTS = (
    ("1d", "1 день"),
    ("7d", "7 дней"),
    ("14d", "14 дней"),
    ("30d", "30 дней"),
    ("90d", "90 дней"),
    ("180d", "180 дней"),
)


def _bool_on(filters: dict, key: str) -> bool:
    return filters.get(key) is True


def _none(v) -> str:
    if v is None or v is False or v == "" or v == []:
        return _NONE
    return str(v)


def _period_label(code: str | None) -> str:
    c = (code or "").strip()
    if not c:
        return _NONE
    for k, lab in _DATE_OPTS + _REG_OPTS:
        if k == c:
            return lab
    return c


def _ok_set(supported: set[str], name: str) -> bool:
    return not supported or name in supported


async def _plat_meta(session, user):
    plat = await get_autoparse_platform(session, user)
    saved = await get_saved_filters(session, user, plat)
    key = await get_autoparse_key(session, user)
    meta: dict = {}
    supported: set[str] = set()
    if key:
        try:
            meta = platform_schema(await fetch_schema(key), plat) or {}
            supported = supported_filter_keys(meta)
        except XProjectError:
            meta = {}
    return plat, saved, supported, meta


async def _save_filters_patch(session, user, **patch) -> None:
    plat = await get_autoparse_platform(session, user)
    saved = await get_saved_filters(session, user, plat)
    for k, v in patch.items():
        if v is None:
            saved.pop(k, None)
        else:
            saved[k] = v
    await set_saved_filters(session, user, plat, saved)


async def _filters_view(session, user) -> tuple[str, InlineKeyboardMarkup]:
    plat, saved, supported, _meta = await _plat_meta(session, user)
    cats = saved.get("categories") if isinstance(saved.get("categories"), list) else []
    if not cats:
        cat_lab = _NONE
    elif len(cats) == 1:
        cat_lab = category_label(cats[0])
    else:
        cat_lab = f"{len(cats)} выбрано"
    pmin, pmax = saved.get("price_min"), saved.get("price_max")
    if pmin is None and pmax is None:
        price_lab = _NONE
    else:
        price_lab = f"{_none(pmin)} – {_none(pmax)}"
    sw = saved.get("stop_words") if isinstance(saved.get("stop_words"), list) else []
    views = saved.get("internal_view_count")
    views_lab = "Уникальные" if views == 0 else _none(views)
    n = await get_json_count(session, user)

    def row_btn(key: str, caption: str, data: str, *, toggle: bool | None = None):
        if toggle is None:
            return [inline_button(key, caption, callback_data=data)]
        return [toggle_button(toggle, caption, data)]

    rows = []
    rows.append([inline_button("refresh", "Подтянуть с XProject", callback_data="apf_sync")])
    if _ok_set(supported, "categories"):
        rows.append(
            [inline_button("presets", f"Категории: {cat_lab}", callback_data="apf_cats:0")]
        )
    if _ok_set(supported, "price_min") or _ok_set(supported, "price_max"):
        rows.append([inline_button("price", f"Цена: {price_lab}", callback_data="apf_price")])
    if _ok_set(supported, "seller_review_count_max"):
        rows.append(
            [
                inline_button(
                    "status",
                    f"Макс. отзывов: {_none(saved.get('seller_review_count_max'))}",
                    callback_data="apf_num:rev",
                )
            ]
        )
    if _ok_set(supported, "seller_listing_count_max"):
        rows.append(
            [
                inline_button(
                    "presets",
                    f"Макс. объяв. продавца: {_none(saved.get('seller_listing_count_max'))}",
                    callback_data="apf_num:ads",
                )
            ]
        )
    if _ok_set(supported, "created_at_period"):
        rows.append(
            [
                inline_button(
                    "interval",
                    f"Дата объявления: {_period_label(saved.get('created_at_period'))}",
                    callback_data="apf_date",
                )
            ]
        )
    if _ok_set(supported, "seller_created_at_period") or _ok_set(
        supported, "seller_created_at_max_period"
    ):
        rmin = _period_label(saved.get("seller_created_at_max_period"))
        rmax = _period_label(saved.get("seller_created_at_period"))
        rows.append(
            [
                inline_button(
                    "user",
                    f"Регистрация: {rmin} / {rmax}",
                    callback_data="apf_reg",
                )
            ]
        )
    if _ok_set(supported, "delivery"):
        on = _bool_on(saved, "delivery")
        rows.append(
            row_btn("ok" if on else "fail", f"Доставка: {'Вкл' if on else 'Выкл'}", "apf_tg:delivery", toggle=on)
        )
    if _ok_set(supported, "seller_email"):
        on = _bool_on(saved, "seller_email")
        rows.append(
            row_btn(
                "email",
                f"Почта продавца: {'Вкл' if on else 'Выкл'}",
                "apf_tg:seller_email",
                toggle=on,
            )
        )
    if _ok_set(supported, "stop_words"):
        rows.append(
            [
                inline_button(
                    "edit",
                    f"Банворды: {len(sw)} шт." if sw else f"Банворды: {_NONE}",
                    callback_data="apf_sw",
                )
            ]
        )
    if _ok_set(supported, "internal_view_count"):
        rows.append(
            [inline_button("search", f"Просмотры в парсере: {views_lab}", callback_data="apf_num:view")]
        )
    rows.append(
        [inline_button("presets", f"Объявлений для выдачи (JSON): {n}", callback_data="autoparse_count")]
    )
    rows.append([inline_button("delete", "Сбросить фильтры", callback_data="apf_reset")])
    rows.append([back_inline("autoparse")])
    text = (
        f"{html_emoji('wrench')} <b>Фильтры авто-парса</b>\n"
        f"{menu_path(('search', 'Авто-парс'), ('wrench', 'Фильтры'))}\n\n"
        f"Площадка: <code>{html.escape(plat)}</code>\n"
        f"<i>Как в XProject: «без фильтра» = любые объявления. "
        f"Количество выдачи — то же, что JSON в авто-парсе.</i>"
    )
    return text, InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(F.data == "autoparse_filters")
async def autoparse_filters(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    async with Session() as session:
        user = await get_or_create_user(session, callback.from_user.id)
        text, kb = await _filters_view(session, user)
    await _edit(callback, text, kb)
    await callback_answer_safe(callback)


@router.callback_query(F.data == "apf_sync")
async def apf_sync(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    async with Session() as session:
        user = await get_or_create_user(session, callback.from_user.id)
        api_key = await get_autoparse_key(session, user)
        plat = await get_autoparse_platform(session, user)
        if not api_key:
            await callback_answer_safe(callback, toast("fail", "Сначала ключ"), show_alert=True)
            return
        try:
            hit = pick_task_for_filters(await list_tasks(api_key), platform=plat)
        except XProjectError as e:
            await callback_answer_safe(callback, toast("fail", str(e)[:80]), show_alert=True)
            return
        if not hit or not isinstance(hit.get("filters"), dict) or not hit.get("filters"):
            await callback_answer_safe(
                callback,
                toast("warn", "Нет задачи этой площадки в API"),
                show_alert=True,
            )
            text, kb = await _filters_view(session, user)
            await _edit(callback, text, kb)
            return
        src = dict(hit["filters"])
        src.pop("internal_listing_count", None)
        await set_saved_filters(session, user, plat, src)
        text, kb = await _filters_view(session, user)
    await _edit(callback, text, kb)
    await callback_answer_safe(
        callback, toast("ok", f"С задачи #{hit.get('task_id')}")
    )


@router.callback_query(F.data.startswith("apf_tg:"))
async def apf_toggle(callback: CallbackQuery, state: FSMContext) -> None:
    field = (callback.data or "").split(":", 1)[-1].strip()
    if field not in {"seller_email", "delivery"}:
        await callback_answer_safe(callback)
        return
    async with Session() as session:
        user = await get_or_create_user(session, callback.from_user.id)
        plat = await get_autoparse_platform(session, user)
        saved = await get_saved_filters(session, user, plat)
        if saved.get(field) is True:
            saved.pop(field, None)
        else:
            saved[field] = True
        await set_saved_filters(session, user, plat, saved)
        text, kb = await _filters_view(session, user)
    await _edit(callback, text, kb)
    await callback_answer_safe(callback)


def _cat_btn(on: bool, lab: str, data: str) -> InlineKeyboardButton:
    """Без style=success/danger — Telegram часто не принимает и не обновляет клавиатуру."""
    return inline_button("green" if on else "red", lab, callback_data=data)


def _categories_kb(cats: list[str], selected: set[str], page: int) -> tuple[str, InlineKeyboardMarkup]:
    pages = max(1, (len(cats) + _CATS_PAGE - 1) // _CATS_PAGE)
    page = max(0, min(page, pages - 1))
    chunk = cats[page * _CATS_PAGE : (page + 1) * _CATS_PAGE]
    rows = []
    row = []
    for i, slug in enumerate(chunk):
        idx = page * _CATS_PAGE + i
        lab = category_label(slug)
        if len(lab) > 24:
            lab = lab[:24]
        row.append(_cat_btn(slug in selected, lab, f"apf_ci:{idx}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append(
        [
            inline_button("ok", "Выбрать все", callback_data="apf_call"),
            inline_button("fail", "Убрать все", callback_data="apf_cnone"),
        ]
    )
    nav = []
    if page > 0:
        nav.append(inline_button("prev", "<", callback_data=f"apf_cats:{page - 1}"))
    nav.append(inline_button("status", f"{page + 1}/{pages}", callback_data=f"apf_cats:{page}"))
    if page + 1 < pages:
        nav.append(inline_button("next", ">", callback_data=f"apf_cats:{page + 1}"))
    rows.append(nav)
    rows.append([back_inline("autoparse_filters")])
    names = [category_label(x) for x in cats if x in selected]
    picked = ", ".join(names[:6]) or _NONE
    extra = f" +{len(names) - 6}" if len(names) > 6 else ""
    text = (
        f"{html_emoji('presets')} <b>Категории</b>\n\n"
        "Нажми категорию — загорится зелёным. «Смотреть везде» — обычная категория.\n"
        f"Сейчас: <b>{html.escape(picked)}{html.escape(extra)}</b> · "
        f"выбрано <b>{len(selected)}</b>/{len(cats)}"
    )
    return text, InlineKeyboardMarkup(inline_keyboard=rows)


async def _cats_list(session, user, state: FSMContext) -> list[str]:
    data = await state.get_data()
    cached = data.get("apf_cat_list")
    if isinstance(cached, list) and cached:
        return [str(x) for x in cached if str(x).strip()]
    _p, _sv, _s, meta = await _plat_meta(session, user)
    cats = schema_category_values(meta)
    if cats:
        await state.update_data(apf_cat_list=cats)
    return cats


async def _show_cats(callback: CallbackQuery, state: FSMContext, page: int) -> None:
    async with Session() as session:
        user = await get_or_create_user(session, callback.from_user.id)
        cats = await _cats_list(session, user, state)
        plat = await get_autoparse_platform(session, user)
        saved = await get_saved_filters(session, user, plat)
    if not cats:
        await callback_answer_safe(callback, toast("fail", "Схема без категорий"), show_alert=True)
        return
    selected = {str(x).strip() for x in (saved.get("categories") or []) if str(x).strip()}
    text, kb = _categories_kb(cats, selected, page)
    await _edit(callback, text, kb)
    await callback_answer_safe(callback)


@router.callback_query(F.data.startswith("apf_cats:"))
async def apf_cats(callback: CallbackQuery, state: FSMContext) -> None:
    try:
        page = int((callback.data or "").split(":")[-1])
    except ValueError:
        page = 0
    await _show_cats(callback, state, page)


@router.callback_query(F.data.startswith("apf_ci:"))
async def apf_ci(callback: CallbackQuery, state: FSMContext) -> None:
    try:
        idx = int((callback.data or "").split(":")[-1])
    except ValueError:
        await callback_answer_safe(callback)
        return
    async with Session() as session:
        user = await get_or_create_user(session, callback.from_user.id)
        cats = await _cats_list(session, user, state)
        plat = await get_autoparse_platform(session, user)
        saved = await get_saved_filters(session, user, plat)
        if idx < 0 or idx >= len(cats):
            await callback_answer_safe(callback, toast("fail", "Список категорий устарел"), show_alert=True)
            return
        new = toggle_category_list(saved.get("categories"), cats[idx], all_values=cats)
        await _save_filters_patch(session, user, categories=new or None)
    await _show_cats(callback, state, idx // _CATS_PAGE)


@router.callback_query(F.data == "apf_call")
async def apf_call(callback: CallbackQuery, state: FSMContext) -> None:
    async with Session() as session:
        user = await get_or_create_user(session, callback.from_user.id)
        cats = await _cats_list(session, user, state)
        await _save_filters_patch(session, user, categories=list(cats) or None)
    await _show_cats(callback, state, 0)


@router.callback_query(F.data == "apf_cnone")
async def apf_cnone(callback: CallbackQuery, state: FSMContext) -> None:
    async with Session() as session:
        user = await get_or_create_user(session, callback.from_user.id)
        await _save_filters_patch(session, user, categories=None)
    await _show_cats(callback, state, 0)


def _choice_kb(preset_pairs: list[tuple[str, str]], off_data: str, enter_data: str, back: str):
    rows = []
    row = []
    for code, lab in preset_pairs:
        row.append(inline_button("ok", lab, callback_data=code))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append(
        [
            inline_button("fail", _NONE, callback_data=off_data),
            inline_button("write", "Ввести", callback_data=enter_data),
        ]
    )
    rows.append([back_inline(back)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(F.data == "apf_price")
async def apf_price(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    async with Session() as session:
        user = await get_or_create_user(session, callback.from_user.id)
        _p, saved, _s, _m = await _plat_meta(session, user)
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                inline_button(
                    "price",
                    f"Минимум: {_none(saved.get('price_min'))}",
                    callback_data="apf_pmin",
                ),
                inline_button(
                    "price",
                    f"Максимум: {_none(saved.get('price_max'))}",
                    callback_data="apf_pmax",
                ),
            ],
            [back_inline("autoparse_filters")],
        ]
    )
    await _edit(
        callback,
        f"{html_emoji('price')} <b>Цена</b>\n\n"
        "Выберите минимум и максимум. Без фильтра — любые цены.",
        kb,
    )
    await callback_answer_safe(callback)


@router.callback_query(F.data == "apf_pmin")
async def apf_pmin(callback: CallbackQuery, state: FSMContext) -> None:
    await _edit(
        callback,
        f"{html_emoji('price')} <b>Минимум цены</b>",
        InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    inline_button("fail", _NONE, callback_data="apf_pmin_off"),
                    inline_button("write", "Указать цену", callback_data="apf_pmin_in"),
                ],
                [back_inline("apf_price")],
            ]
        ),
    )
    await callback_answer_safe(callback)


@router.callback_query(F.data == "apf_pmax")
async def apf_pmax(callback: CallbackQuery, state: FSMContext) -> None:
    await _edit(
        callback,
        f"{html_emoji('price')} <b>Максимум цены</b>",
        InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    inline_button("fail", _NONE, callback_data="apf_pmax_off"),
                    inline_button("write", "Указать цену", callback_data="apf_pmax_in"),
                ],
                [back_inline("apf_price")],
            ]
        ),
    )
    await callback_answer_safe(callback)


@router.callback_query(F.data == "apf_pmin_off")
async def apf_pmin_off(callback: CallbackQuery, state: FSMContext) -> None:
    async with Session() as session:
        user = await get_or_create_user(session, callback.from_user.id)
        await _save_filters_patch(session, user, price_min=None)
    await apf_price(callback, state)


@router.callback_query(F.data == "apf_pmax_off")
async def apf_pmax_off(callback: CallbackQuery, state: FSMContext) -> None:
    async with Session() as session:
        user = await get_or_create_user(session, callback.from_user.id)
        await _save_filters_patch(session, user, price_max=None)
    await apf_price(callback, state)


@router.callback_query(F.data == "apf_pmin_in")
async def apf_pmin_in(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AutoparseState.waiting_price_min)
    await _edit(
        callback,
        f"{html_emoji('price')} Пришли число — минимум цены.",
        InlineKeyboardMarkup(inline_keyboard=[[back_inline("apf_price")]]),
    )
    await callback_answer_safe(callback)


@router.callback_query(F.data == "apf_pmax_in")
async def apf_pmax_in(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AutoparseState.waiting_price_max)
    await _edit(
        callback,
        f"{html_emoji('price')} Пришли число — максимум цены.",
        InlineKeyboardMarkup(inline_keyboard=[[back_inline("apf_price")]]),
    )
    await callback_answer_safe(callback)


_NUM_KIND = {
    "rev": ("seller_review_count_max", "Максимум отзывов", [(0, "0"), (5, "5"), (15, "15")]),
    "ads": ("seller_listing_count_max", "Максимум объявлений", [(1, "1"), (5, "5"), (15, "15")]),
    "view": ("internal_view_count", "Просмотры в парсере", [(0, "Уникальные объявления")]),
}


@router.callback_query(F.data.startswith("apf_num:"))
async def apf_num(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    kind = (callback.data or "").split(":")[-1]
    spec = _NUM_KIND.get(kind)
    if not spec:
        await callback_answer_safe(callback)
        return
    field, title, presets = spec
    pairs = [(f"apf_nv:{kind}:{v}", lab) for v, lab in presets]
    extra = ""
    if kind == "view":
        extra = "\nМаксимум, сколько раз объявление уже отдавалось парсером. 0 — только уникальные."
    elif kind == "rev":
        extra = "\nПродавцы с большим числом отзывов отсекаются."
    await _edit(
        callback,
        f"{html_emoji('status')} <b>{html.escape(title)}</b>\n\n"
        f"Выберите значение, снимите фильтр или введите своё.{extra}",
        _choice_kb(pairs, f"apf_nv:{kind}:off", f"apf_nin:{kind}", "autoparse_filters"),
    )
    await callback_answer_safe(callback)


@router.callback_query(F.data.startswith("apf_nv:"))
async def apf_nv(callback: CallbackQuery, state: FSMContext) -> None:
    parts = (callback.data or "").split(":")
    if len(parts) < 3:
        await callback_answer_safe(callback)
        return
    kind, raw = parts[1], parts[2]
    spec = _NUM_KIND.get(kind)
    if not spec:
        await callback_answer_safe(callback)
        return
    field = spec[0]
    async with Session() as session:
        user = await get_or_create_user(session, callback.from_user.id)
        if raw == "off":
            await _save_filters_patch(session, user, **{field: None})
        else:
            try:
                await _save_filters_patch(session, user, **{field: int(raw)})
            except ValueError:
                await callback_answer_safe(callback)
                return
        text, kb = await _filters_view(session, user)
    await _edit(callback, text, kb)
    await callback_answer_safe(callback, toast("ok", "Ок"))


@router.callback_query(F.data.startswith("apf_nin:"))
async def apf_nin(callback: CallbackQuery, state: FSMContext) -> None:
    kind = (callback.data or "").split(":")[-1]
    if kind not in _NUM_KIND:
        await callback_answer_safe(callback)
        return
    await state.set_state(AutoparseState.waiting_num)
    await state.update_data(apf_num_kind=kind)
    await _edit(
        callback,
        f"{html_emoji('write')} Пришли число для фильтра.",
        InlineKeyboardMarkup(inline_keyboard=[[back_inline(f"apf_num:{kind}")]]),
    )
    await callback_answer_safe(callback)


@router.callback_query(F.data == "apf_date")
async def apf_date(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    pairs = [(f"apf_dv:{code}", lab) for code, lab in _DATE_OPTS]
    await _edit(
        callback,
        f"{html_emoji('interval')} <b>Дата объявления</b>\n\n"
        "Выберите одно из значений ниже или введите значение.",
        _choice_kb(pairs, "apf_dv:off", "apf_din", "autoparse_filters"),
    )
    await callback_answer_safe(callback)


@router.callback_query(F.data.startswith("apf_dv:"))
async def apf_dv(callback: CallbackQuery, state: FSMContext) -> None:
    raw = (callback.data or "").split(":", 1)[-1]
    async with Session() as session:
        user = await get_or_create_user(session, callback.from_user.id)
        if raw == "off":
            await _save_filters_patch(session, user, created_at_period=None)
        else:
            await _save_filters_patch(session, user, created_at_period=raw)
        text, kb = await _filters_view(session, user)
    await _edit(callback, text, kb)
    await callback_answer_safe(callback, toast("ok", "Ок"))


@router.callback_query(F.data == "apf_din")
async def apf_din(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AutoparseState.waiting_period)
    await state.update_data(apf_period_field="created_at_period")
    await _edit(
        callback,
        f"{html_emoji('write')} Период: <code>fresh</code>, <code>1h</code>, <code>3h</code>, "
        f"<code>1d</code>, <code>7d</code>…",
        InlineKeyboardMarkup(inline_keyboard=[[back_inline("apf_date")]]),
    )
    await callback_answer_safe(callback)


@router.callback_query(F.data == "apf_reg")
async def apf_reg(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    async with Session() as session:
        user = await get_or_create_user(session, callback.from_user.id)
        _p, saved, _s, _m = await _plat_meta(session, user)
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                inline_button(
                    "user",
                    f"Минимум: {_period_label(saved.get('seller_created_at_max_period'))}",
                    callback_data="apf_regside:min",
                ),
                inline_button(
                    "user",
                    f"Максимум: {_period_label(saved.get('seller_created_at_period'))}",
                    callback_data="apf_regside:max",
                ),
            ],
            [back_inline("autoparse_filters")],
        ]
    )
    await _edit(
        callback,
        f"{html_emoji('user')} <b>Дата регистрации продавца</b>\n\n"
        "Минимум — аккаунт не моложе. Максимум — аккаунт не старше. Без фильтра — любые.",
        kb,
    )
    await callback_answer_safe(callback)


@router.callback_query(F.data.startswith("apf_regside:"))
async def apf_regside(callback: CallbackQuery, state: FSMContext) -> None:
    side = (callback.data or "").split(":")[-1]
    field = "seller_created_at_max_period" if side == "min" else "seller_created_at_period"
    title = "Минимум (возраст не меньше)" if side == "min" else "Максимум (возраст не больше)"
    pairs = [(f"apf_rv:{side}:{code}", lab) for code, lab in _REG_OPTS]
    await _edit(
        callback,
        f"{html_emoji('user')} <b>{html.escape(title)}</b>",
        _choice_kb(pairs, f"apf_rv:{side}:off", f"apf_rin:{side}", "apf_reg"),
    )
    await callback_answer_safe(callback)


@router.callback_query(F.data.startswith("apf_rv:"))
async def apf_rv(callback: CallbackQuery, state: FSMContext) -> None:
    parts = (callback.data or "").split(":")
    if len(parts) < 3:
        await callback_answer_safe(callback)
        return
    side, raw = parts[1], parts[2]
    field = "seller_created_at_max_period" if side == "min" else "seller_created_at_period"
    async with Session() as session:
        user = await get_or_create_user(session, callback.from_user.id)
        await _save_filters_patch(session, user, **{field: None if raw == "off" else raw})
    await apf_reg(callback, state)


@router.callback_query(F.data.startswith("apf_rin:"))
async def apf_rin(callback: CallbackQuery, state: FSMContext) -> None:
    side = (callback.data or "").split(":")[-1]
    field = "seller_created_at_max_period" if side == "min" else "seller_created_at_period"
    await state.set_state(AutoparseState.waiting_reg)
    await state.update_data(apf_reg_field=field)
    await _edit(
        callback,
        f"{html_emoji('write')} Период: <code>1d</code>, <code>7d</code>, <code>30d</code>…",
        InlineKeyboardMarkup(inline_keyboard=[[back_inline("apf_reg")]]),
    )
    await callback_answer_safe(callback)


@router.callback_query(F.data == "apf_reset")
async def apf_reset(callback: CallbackQuery, state: FSMContext) -> None:
    async with Session() as session:
        user = await get_or_create_user(session, callback.from_user.id)
        plat = await get_autoparse_platform(session, user)
        await set_saved_filters(session, user, plat, {})
        text, kb = await _filters_view(session, user)
    await _edit(callback, text, kb)
    await callback_answer_safe(callback, toast("ok", "Сброшено"))


@router.callback_query(F.data == "apf_sw")
async def apf_sw(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AutoparseState.waiting_stop_words)
    await _edit(
        callback,
        f"{html_emoji('edit')} <b>Банворды</b>\n\n"
        "Слова через запятую или с новой строки. Пустое сообщение — снять фильтр.",
        InlineKeyboardMarkup(inline_keyboard=[[back_inline("autoparse_filters")]]),
    )
    await callback_answer_safe(callback)


async def _show_filters_after_msg(message: Message, state: FSMContext) -> None:
    await state.clear()
    async with Session() as session:
        user = await get_or_create_user(session, message.from_user.id)
        text, kb = await _filters_view(session, user)
    await message.answer(text, reply_markup=kb, parse_mode="HTML")


@router.message(AutoparseState.waiting_price_min)
async def apf_pmin_save(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip().replace(",", ".")
    async with Session() as session:
        user = await get_or_create_user(session, message.from_user.id)
        plat = await get_autoparse_platform(session, user)
        saved = await get_saved_filters(session, user, plat)
        try:
            n = float(raw)
        except ValueError:
            await message.answer(msg_fail("Нужно число."))
            return
        if n <= 0:
            saved.pop("price_min", None)
        else:
            saved["price_min"] = n
        await set_saved_filters(session, user, plat, saved)
    await _show_filters_after_msg(message, state)


@router.message(AutoparseState.waiting_price_max)
async def apf_pmax_save(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip().replace(",", ".")
    async with Session() as session:
        user = await get_or_create_user(session, message.from_user.id)
        plat = await get_autoparse_platform(session, user)
        saved = await get_saved_filters(session, user, plat)
        try:
            n = float(raw)
        except ValueError:
            await message.answer(msg_fail("Нужно число."))
            return
        if n <= 0:
            saved.pop("price_max", None)
        else:
            saved["price_max"] = n
        await set_saved_filters(session, user, plat, saved)
    await _show_filters_after_msg(message, state)


@router.message(AutoparseState.waiting_stop_words)
async def apf_sw_save(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    async with Session() as session:
        user = await get_or_create_user(session, message.from_user.id)
        plat = await get_autoparse_platform(session, user)
        saved = await get_saved_filters(session, user, plat)
        if not raw:
            saved.pop("stop_words", None)
        else:
            parts = [p.strip() for chunk in raw.split("\n") for p in chunk.split(",")]
            words = [p for p in parts if p]
            if words:
                saved["stop_words"] = words
            else:
                saved.pop("stop_words", None)
        await set_saved_filters(session, user, plat, saved)
    await _show_filters_after_msg(message, state)


@router.message(AutoparseState.waiting_num)
async def apf_num_save(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    kind = str(data.get("apf_num_kind") or "")
    spec = _NUM_KIND.get(kind)
    if not spec:
        await state.clear()
        await message.answer(msg_fail("Фильтр сброшен, открой меню ещё раз."))
        return
    raw = (message.text or "").strip()
    try:
        n = int(float(raw.replace(",", ".")))
    except ValueError:
        await message.answer(msg_fail("Нужно число."))
        return
    async with Session() as session:
        user = await get_or_create_user(session, message.from_user.id)
        await _save_filters_patch(session, user, **{spec[0]: n})
    await _show_filters_after_msg(message, state)


@router.message(AutoparseState.waiting_period)
async def apf_period_save(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    field = str(data.get("apf_period_field") or "created_at_period")
    raw = (message.text or "").strip().lower()
    if not raw:
        await message.answer(msg_fail("Пришли период, например 7d."))
        return
    async with Session() as session:
        user = await get_or_create_user(session, message.from_user.id)
        await _save_filters_patch(session, user, **{field: raw})
    await _show_filters_after_msg(message, state)


@router.message(AutoparseState.waiting_reg)
async def apf_reg_save(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    field = str(data.get("apf_reg_field") or "seller_created_at_period")
    raw = (message.text or "").strip().lower()
    if not raw:
        await message.answer(msg_fail("Пришли период, например 30d."))
        return
    async with Session() as session:
        user = await get_or_create_user(session, message.from_user.id)
        await _save_filters_patch(session, user, **{field: raw})
    await _show_filters_after_msg(message, state)


@router.callback_query(F.data == "autoparse_start")
async def autoparse_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    if bg_is_running(callback.from_user.id, "autoparse"):
        await callback_answer_safe(callback, toast("wait", "Уже запущено"), show_alert=True)
        return
    async with Session() as session:
        user = await get_or_create_user(session, callback.from_user.id)
        key = await get_autoparse_key(session, user)
    if not key:
        await callback_answer_safe(callback, toast("fail", "Сначала ключ"), show_alert=True)
        return
    await _edit(
        callback,
        f"{html_emoji('send')} <b>Сколько батчей</b>\n\n"
        "1 / 5 / 10 — столько раз спарсить JSON и сразу прогнать валидацию.\n"
        "0 (∞) — пока не нажмёшь Стоп или парсер не отдаст 402.",
        _batches_kb(),
    )
    await callback_answer_safe(callback)


@router.callback_query(F.data == "autoparse_stop")
async def autoparse_stop_cb(callback: CallbackQuery, state: FSMContext) -> None:
    bg_cancel(callback.from_user.id, "autoparse")
    await callback_answer_safe(callback, toast("ok", "Стоп"))
    await autoparse_open(callback, state)


@router.message(Command("stopparse"))
async def stopparse_cmd(message: Message, state: FSMContext) -> None:
    if bg_cancel(message.from_user.id, "autoparse"):
        await message.answer(msg_ok("Авто-парс остановлен."), parse_mode="HTML")
    else:
        await message.answer(msg_wait("Авто-парс сейчас не идёт."), parse_mode="HTML")


@router.callback_query(F.data.startswith("autoparse_run:"))
async def autoparse_run(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    raw = (callback.data or "").split(":", 1)[-1].strip()
    try:
        batches = int(raw)
    except ValueError:
        await callback_answer_safe(callback)
        return
    if batches not in {0, 1, 5, 10}:
        await callback_answer_safe(callback, toast("fail", "Только 1/5/10/0"), show_alert=True)
        return
    tg_id = callback.from_user.id
    if bg_is_running(tg_id, "autoparse"):
        await callback_answer_safe(callback, toast("wait", "Уже запущено"), show_alert=True)
        return
    bot = callback.bot
    chat_id = callback.message.chat.id
    uname = callback.from_user.username

    async def _job() -> None:
        await _run_autoparse_loop(
            bot, chat_id, tg_id, uname, batches=batches
        )

    if not bg_start(tg_id, "autoparse", _job()):
        await callback_answer_safe(callback, toast("wait", "Уже запущено"), show_alert=True)
        return
    await callback_answer_safe(callback, toast("ok", "Старт"))
    label = "∞" if batches == 0 else str(batches)
    try:
        await callback.message.answer(
            f"{html_emoji('search')} Авто-парс: <b>{html.escape(label)}</b> батч(ей). "
            f"Стоп: /stopparse",
            parse_mode="HTML",
        )
    except Exception:
        pass


async def _collect_listings(
    api_key: str,
    task_id: int,
    need: int,
    seen: set[int],
    *,
    infinite: bool,
    status_msg=None,
    batch_label: str = "",
    plat: str = "",
    src: str = "",
) -> list[dict]:
    out: list[dict] = []
    cursor: int | None = None
    idle = 0
    polls = 0
    max_idle = 12 if infinite else 8

    async def _tick(*, page_n: int, added: int, waiting: bool) -> None:
        if status_msg is None:
            return
        wait_line = (
            f"\nПусто · пауза 8 с · простой {idle}/{max_idle}"
            if waiting
            else f"\n+{added} новых на этой странице"
        )
        try:
            await status_msg.edit_text(
                f"{html_emoji('search')} <b>Парсер ищет</b>\n"
                f"Батч <b>{html.escape(batch_label)}</b> · "
                f"<code>{html.escape(plat)}</code> · задача <code>#{int(task_id)}</code>\n"
                f"Собрано: <b>{len(out)}</b> / {int(need)}\n"
                f"Опрос API: <b>{polls}</b> · на странице: <b>{page_n}</b>"
                f"{wait_line}\n"
                f"<i>{html.escape(src)}</i>",
                parse_mode="HTML",
            )
        except Exception:
            pass

    while len(out) < need:
        page = await fetch_listings(api_key, task_id, cursor=cursor)
        polls += 1
        listings = page.get("listings") if isinstance(page.get("listings"), list) else []
        added = 0
        for raw in listings:
            if not isinstance(raw, dict):
                continue
            try:
                rid = int(raw.get("row_id") or 0)
            except (TypeError, ValueError):
                rid = 0
            if rid and rid in seen:
                continue
            if rid:
                seen.add(rid)
            out.append(listing_to_item(raw))
            added += 1
            if len(out) >= need:
                break
        await _tick(page_n=len(listings), added=added, waiting=False)
        if len(out) >= need:
            break
        if page.get("has_more") and page.get("next_cursor") is not None:
            try:
                cursor = int(page.get("next_cursor"))
            except (TypeError, ValueError):
                cursor = None
            idle = 0
            continue
        cursor = None
        idle += 1
        if added == 0 and idle >= max_idle:
            break
        await _tick(page_n=len(listings), added=added, waiting=True)
        await asyncio.sleep(8)
    return out


async def _start_or_reuse(api_key: str, platform: str, filters: dict) -> tuple[int, bool]:
    """→ (task_id, created_here). created_here=False — чужая задача, не стопаем."""
    try:
        task = await start_task(api_key, platform=platform, filters=filters)
        return int(task.get("task_id")), True
    except XProjectError as e:
        if e.status != 409:
            raise
        tasks = await list_tasks(api_key)
        hit = pick_existing_task(tasks, platform=platform)
        if hit:
            return int(hit["task_id"]), False
        raise


async def _run_autoparse_loop(
    bot,
    chat_id: int,
    tg_id: int,
    username: str | None,
    *,
    batches: int,
) -> None:
    from handlers.validation import run_validation_items

    infinite = batches == 0
    seen: set[int] = set()
    task_id: int | None = None
    api_key = ""
    created_here = False
    try:
        async with Session() as session:
            user = await get_or_create_user(session, tg_id)
            api_key = await get_autoparse_key(session, user)
            cc = await get_autoparse_country(session, user)
            plat = await get_autoparse_platform(session, user)
            need = await get_json_count(session, user)
        schema = await fetch_schema(api_key)
        meta = platform_schema(schema, plat)
        if not meta:
            await bot.send_message(
                chat_id,
                msg_fail(
                    f"Площадка <code>{html.escape(plat)}</code> нет в схеме парсера "
                    f"для этой страны."
                ),
                parse_mode="HTML",
            )
            return
        existing = pick_task_for_filters(await list_tasks(api_key), platform=plat)
        saved: dict = {}
        async with Session() as session:
            user = await get_or_create_user(session, tg_id)
            saved = await get_saved_filters(session, user, plat)
            filters, src = resolve_local_start_filters(
                plat=meta,
                bot_cc=cc,
                json_count=need,
                infinite=infinite,
                saved=saved,
                xp_task=existing,
            )
            if existing and isinstance(existing.get("filters"), dict) and existing.get("filters"):
                store = dict(existing["filters"])
                store.pop("internal_listing_count", None)
                await set_saved_filters(session, user, plat, store)
                src = f"XProject задача #{existing.get('task_id')} (сохранил)"
        done = 0
        while infinite or done < batches:
            task_id, created_here = await _start_or_reuse(api_key, plat, filters)
            batch_label = f"{done + 1}" if infinite else f"{done + 1}/{batches}"
            status = await bot.send_message(
                chat_id,
                f"{html_emoji('wait')} Парсер: батч <b>{html.escape(batch_label)}</b> · "
                f"<code>{html.escape(plat)}</code> · задача <code>#{int(task_id)}</code>\n"
                f"Стартую выдачу JSON {need}…\n"
                f"<i>{html.escape(src)}</i>",
                parse_mode="HTML",
            )
            items = await _collect_listings(
                api_key,
                task_id,
                need,
                seen,
                infinite=infinite,
                status_msg=status,
                batch_label=batch_label,
                plat=plat,
                src=src,
            )
            if not items:
                try:
                    await status.edit_text(
                        f"{html_emoji('warn')} Батч {done + 1}: парсер пока пустой.",
                        parse_mode="HTML",
                    )
                except Exception:
                    pass
                if not infinite:
                    break
                await asyncio.sleep(20)
                continue
            try:
                await status.edit_text(
                    f"{html_emoji('search')} <b>Авто-парс · валидация</b>\n"
                    f"Батч <b>{done + 1}</b> · в JSON: <b>{len(items)}</b>",
                    parse_mode="HTML",
                )
            except Exception:
                pass
            await run_validation_items(
                bot=bot,
                chat_id=chat_id,
                tg_id=tg_id,
                items=items,
                status_msg=status,
                country_override=cc,
                username=username,
            )
            done += 1
            if not infinite and created_here and task_id:
                try:
                    await stop_task(api_key, task_id)
                except XProjectError:
                    pass
                task_id = None
        await bot.send_message(
            chat_id,
            msg_ok(f"Авто-парс закончил. Батчей: {done}."),
            parse_mode="HTML",
        )
    except asyncio.CancelledError:
        if api_key and task_id and created_here:
            try:
                await stop_task(api_key, task_id)
            except Exception:
                pass
        try:
            await bot.send_message(
                chat_id,
                f"{html_emoji('warn')} Авто-парс остановлен.",
                parse_mode="HTML",
            )
        except Exception:
            pass
        raise
    except XProjectError as e:
        try:
            await bot.send_message(chat_id, msg_fail(str(e)), parse_mode="HTML")
        except Exception:
            pass
    except Exception:
        logger.exception("autoparse loop tg=%s", tg_id)
        try:
            await bot.send_message(
                chat_id,
                msg_fail("Авто-парс упал. Смотри логи."),
                parse_mode="HTML",
            )
        except Exception:
            pass
    finally:
        if api_key and task_id and created_here:
            try:
                await stop_task(api_key, task_id)
            except Exception:
                pass
