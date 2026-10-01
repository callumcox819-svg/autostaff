import asyncio
import logging
import os
import time

from aiogram import Router, F
from aiogram.types import Message, ReplyKeyboardRemove
from aiogram.exceptions import TelegramRetryAfter
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext

from keyboards.main_menu import main_menu_inline_kb
from database import db_session
from services.users import get_or_create_user
from services.bot_roles import config_admin_ids
from services.bot_access import deny_access_message
from utils.tg_flood import tg_call
from utils.ui_emoji import html_emoji, msg_fail, msg_wait

router = Router()
logger = logging.getLogger(__name__)

# Короткий wait: при чужой рассылке пул занят — лучше кэш, чем 12с зависания.
_START_DB_TIMEOUT_SEC = float(os.getenv("START_DB_TIMEOUT_SEC", "3"))


def _welcome_html() -> str:
    return "\n".join(
        [
            f"{html_emoji('burst')} <b>Mail Bot</b>",
            "Рассылка, входящие, валидация и ссылки.",
            "",
            f"{html_emoji('send')} <code>/send</code> — burst-рассылка",
            f"{html_emoji('stop')} <code>/stop</code> — остановка",
            f"{html_emoji('refresh')} <code>/reset</code> — сброс очереди",
            f"{html_emoji('status')} <code>/stat</code> — статус",
            f"{html_emoji('settings')} <code>/menu</code> — кнопки (не перекрывают чат)",
            "",
            f"{html_emoji('presets')} JSON / TXT — валидация и база офферов",
            f"{html_emoji('settings')} Настройки — аккаунты, прокси, ключ, пресеты",
        ]
    )


async def _answer_welcome(message: Message, *, tg_id: int, show_admin: bool) -> None:
    kb = main_menu_inline_kb(tg_id, show_admin=show_admin)
    try:
        await tg_call(
            lambda: message.answer(_welcome_html(), reply_markup=kb, parse_mode="HTML")
        )
    except TelegramRetryAfter:
        await message.answer(
            "Телеграм временно режет сообщения. Подожди 15–20 секунд и снова /start.",
        )


def _remember_access(tg_id: int, *, is_admin: bool, has_access: bool) -> None:
    try:
        from middlewares.bot_access import _ACCESS_CACHE

        _ACCESS_CACHE[int(tg_id)] = (bool(is_admin), bool(has_access), time.monotonic())
    except Exception:
        pass


def _cached_start_access(tg_id: int) -> tuple[bool, bool] | None:
    """(is_admin, has_access) из middleware-кэша — без Postgres."""
    try:
        from middlewares.bot_access import _ACCESS_STALE_OK_SEC, _cached_access

        return _cached_access(int(tg_id), max_age_sec=_ACCESS_STALE_OK_SEC)
    except Exception:
        return None


async def _start_load_user(tg_id: int) -> tuple[bool, bool, bool]:
    """(is_banned, is_admin, has_access) — один round-trip к БД."""
    async with db_session() as session:
        user = await get_or_create_user(session, tg_id)
        if getattr(user, "is_banned", False):
            return True, False, False
        is_admin = bool(getattr(user, "is_admin", False))
        if is_admin and not bool(getattr(user, "access_granted", False)):
            user.access_granted = True
            await session.commit()
        has_access = is_admin or bool(getattr(user, "access_granted", False))
        return False, is_admin, has_access


async def _ensure_user_bg(tg_id: int) -> None:
    """Создать User в БД без блокировки UI (кэш /start раньше мог пропустить create)."""
    try:
        async with db_session() as session:
            await get_or_create_user(session, int(tg_id))
    except Exception:
        logger.exception("ensure user failed tg=%s", tg_id)


@router.message(CommandStart())
@router.message(F.text.in_({"/ping", "/health"}))
async def cmd_start(message: Message, state: FSMContext) -> None:
    tg_id = int(message.from_user.id)
    text = (message.text or "").strip().lower()
    if text in ("/ping", "/health"):
        await message.answer("pong")
        return

    logger.info("▶ HANDLER /start tg=%s", tg_id)
    try:
        await state.clear()
    except Exception:
        pass

    # Всегда досоздаём User (тест маил / настройки читают строку в БД).
    asyncio.create_task(_ensure_user_bg(tg_id))

    if tg_id in config_admin_ids():
        _remember_access(tg_id, is_admin=True, has_access=True)
        await _answer_welcome(message, tg_id=tg_id, show_admin=True)
        return

    # Во время чужой рассылки Postgres может не ответить — меню из кэша доступа.
    cached = _cached_start_access(tg_id)
    if cached is not None:
        is_admin, has_access = cached
        if has_access or is_admin:
            await _answer_welcome(message, tg_id=tg_id, show_admin=is_admin)
            return

    try:
        is_banned, is_admin, has_access = await asyncio.wait_for(
            _start_load_user(tg_id),
            timeout=_START_DB_TIMEOUT_SEC,
        )
    except asyncio.TimeoutError:
        logger.error("/start DB timeout tg=%s", tg_id)
        # Повторный stale/cache после короткого wait (мог появиться от другого апдейта)
        cached2 = _cached_start_access(tg_id)
        if cached2 is not None and (cached2[0] or cached2[1]):
            await _answer_welcome(message, tg_id=tg_id, show_admin=cached2[0])
            return
        await message.answer(
            f"{msg_wait('БД не отвечает — повтори /start через 15 сек.')}",
            parse_mode="HTML",
        )
        return
    except Exception:
        logger.exception("/start failed tg=%s", tg_id)
        await message.answer(
            f"{msg_fail('Ошибка БД — повтори /start через 10 сек.')}",
            parse_mode="HTML",
        )
        return

    if is_banned:
        _remember_access(tg_id, is_admin=False, has_access=False)
        await message.answer(
            f"{msg_fail('Аккаунт заблокирован.')}",
            reply_markup=ReplyKeyboardRemove(),
            parse_mode="HTML",
        )
        return

    if not has_access:
        _remember_access(tg_id, is_admin=False, has_access=False)
        await deny_access_message(message)
        return

    _remember_access(tg_id, is_admin=is_admin, has_access=True)
    await _answer_welcome(message, tg_id=tg_id, show_admin=is_admin)
