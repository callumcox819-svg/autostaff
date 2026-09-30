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
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from database import Session
from services.autoparse import (
    build_start_filters,
    default_platform_for_country,
    get_autoparse_country,
    get_autoparse_key,
    get_autoparse_platform,
    get_json_count,
    listing_to_item,
    platform_schema,
    set_autoparse_country,
    set_autoparse_key,
    set_json_count,
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
    run = "идёт" if running else "стоп"
    return (
        f"{html_emoji('search')} <b>Авто-парс</b>\n"
        f"{menu_path(('settings', 'Настройки'), ('search', 'Авто-парс'))}\n\n"
        f"<b>Ключ:</b> <code>{html.escape(_mask_key(key))}</code>\n"
        f"<b>Страна:</b> <b>{html.escape(cname(cc))}</b> · площадка <code>{html.escape(plat)}</code>\n"
        f"<b>Объявлений в JSON:</b> <code>{n}</code>\n"
        f"<b>Статус:</b> {html.escape(run)}\n\n"
        "Ключ — <code>X-API-Key</code> с XProject. Запуск: 1 / 5 / 10 батчей "
        "или 0 — пока не остановишь или не кончится подписка (402).\n"
        "Остановка: кнопка Стоп или <code>/stopparse</code>."
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
) -> list[dict]:
    out: list[dict] = []
    cursor: int | None = None
    idle = 0
    max_idle = 12 if infinite else 8
    while len(out) < need:
        page = await fetch_listings(api_key, task_id, cursor=cursor)
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
        await asyncio.sleep(8)
    return out


async def _start_or_reuse(api_key: str, platform: str, filters: dict) -> int:
    try:
        task = await start_task(api_key, platform=platform, filters=filters)
        return int(task.get("task_id"))
    except XProjectError as e:
        if e.status != 409:
            raise
        tasks = await list_tasks(api_key)
        for t in tasks:
            if str(t.get("platform") or "").lower() == platform:
                return int(t["task_id"])
        if tasks:
            return int(tasks[0]["task_id"])
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
        filters = build_start_filters(meta, bot_cc=cc, json_count=need, infinite=infinite)
        done = 0
        while infinite or done < batches:
            task_id = await _start_or_reuse(api_key, plat, filters)
            status = await bot.send_message(
                chat_id,
                f"{html_emoji('wait')} Парсер: батч <b>{done + 1}</b>"
                f"{'' if infinite else f'/{batches}'} · "
                f"<code>{html.escape(plat)}</code> · жду {need} объяв.",
                parse_mode="HTML",
            )
            items = await _collect_listings(
                api_key, task_id, need, seen, infinite=infinite
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
            if not infinite:
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
        if api_key and task_id:
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
        if api_key and task_id:
            try:
                await stop_task(api_key, task_id)
            except Exception:
                pass
