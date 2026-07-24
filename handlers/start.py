import asyncio
import logging
import os

from aiogram import Router, F
from aiogram.types import Message, ReplyKeyboardRemove
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext

from keyboards.main_menu import main_menu_kb
from database import db_session
from services.users import get_or_create_user
from services.bot_roles import config_admin_ids
from services.bot_access import deny_access_message
from utils.ui_emoji import html_emoji, msg_fail, msg_wait

router = Router()
logger = logging.getLogger(__name__)

_START_DB_TIMEOUT_SEC = float(os.getenv("START_DB_TIMEOUT_SEC", "12"))


def _welcome_html() -> str:
    return "\n".join(
        [
            f"{html_emoji('burst')} <b>GAG · Швейцария</b>",
            "Рассылка, входящие, валидация и ссылки.",
            "",
            f"{html_emoji('send')} <code>/send</code> — burst-рассылка",
            f"{html_emoji('stop')} <code>/stop</code> — остановка",
            f"{html_emoji('refresh')} <code>/reset</code> — сброс очереди",
            f"{html_emoji('status')} <code>/stat</code> — статус",
            "",
            f"{html_emoji('presets')} JSON / TXT — валидация и база офферов",
            f"{html_emoji('settings')} Кнопка «Настройки» — аккаунты, прокси, ключ, пресеты",
        ]
    )


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

    welcome = _welcome_html()

    if tg_id in config_admin_ids():
        await message.answer(
            welcome,
            reply_markup=main_menu_kb(tg_id, show_admin=True),
            parse_mode="HTML",
        )
        return

    try:
        is_banned, is_admin, has_access = await asyncio.wait_for(
            _start_load_user(tg_id),
            timeout=_START_DB_TIMEOUT_SEC,
        )
    except asyncio.TimeoutError:
        logger.error("/start DB timeout tg=%s", tg_id)
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
        await message.answer(
            f"{msg_fail('Аккаунт заблокирован.')}",
            reply_markup=ReplyKeyboardRemove(),
            parse_mode="HTML",
        )
        return

    if not has_access:
        await deny_access_message(message)
        return

    await message.answer(
        welcome,
        reply_markup=main_menu_kb(tg_id, show_admin=is_admin),
        parse_mode="HTML",
    )
