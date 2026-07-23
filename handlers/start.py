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

router = Router()
logger = logging.getLogger(__name__)

_START_DB_TIMEOUT_SEC = float(os.getenv("START_DB_TIMEOUT_SEC", "12"))

_WELCOME = (
    "привет даун ебаный\n"
    "ты воркаешь лутаешь мне бабки\n\n"
    "/send — рассылка\n"
    "/stop — стоп\n"
    "/reset — сброс\n"
    "/stat — статус\n\n"
    "json → валидация"
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

    if tg_id in config_admin_ids():
        await message.answer(_WELCOME, reply_markup=main_menu_kb(tg_id, show_admin=True))
        return

    try:
        is_banned, is_admin, has_access = await asyncio.wait_for(
            _start_load_user(tg_id),
            timeout=_START_DB_TIMEOUT_SEC,
        )
    except asyncio.TimeoutError:
        logger.error("/start DB timeout tg=%s", tg_id)
        await message.answer("бд не отвечает, /start через 15 сек")
        return
    except Exception:
        logger.exception("/start failed tg=%s", tg_id)
        await message.answer("ошибка бд, /start через 10 сек")
        return

    if is_banned:
        await message.answer("заблокирован", reply_markup=ReplyKeyboardRemove())
        return

    if not has_access:
        await deny_access_message(message)
        return

    await message.answer(_WELCOME, reply_markup=main_menu_kb(tg_id, show_admin=is_admin))
