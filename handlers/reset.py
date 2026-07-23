"""Команда /reset — очистить очередь рассылки, лиды в БД остаются."""

from __future__ import annotations

import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from database import Session
from keyboards.main_menu import main_menu_kb
from services.mailing_reset import reset_user_mailing_queue
from services.users import get_or_create_user

logger = logging.getLogger(__name__)

router = Router(name="reset")


@router.message(Command("reset"))
async def cmd_reset(message: Message) -> None:
    tg_id = int(message.from_user.id)

    try:
        async with Session() as session:
            user = await get_or_create_user(session, tg_id)
            result = await reset_user_mailing_queue(
                session,
                int(user.id),
                tg_user_id=tg_id,
            )
            await session.commit()
    except Exception:
        logger.exception("cmd_reset failed tg=%s", tg_id)
        await message.answer(
            "❌ Не удалось сбросить очередь. Попробуйте ещё раз.",
            reply_markup=main_menu_kb(tg_id),
        )
        return

    removed = int(result.get("removed") or 0)
    skip_n = int(result.get("skip_emails") or 0)

    if removed == 0:
        lines = [
            "🔄 <b>Очередь рассылки пуста</b>",
            "Нет email в очереди — сбрасывать нечего.",
            "📧 Объявления в БД на месте.",
            "📨 После новой валидации в очередь попадут <b>только новые</b> адреса.",
        ]
    else:
        lines = [
            "🔄 <b>Очередь рассылки обнулена</b>",
            f"Убрано из очереди: <b>{removed}</b> адресов.",
            "📧 <b>Объявления в БД</b> — без изменений.",
            "📨 Следующая валидация <b>не вернёт</b> эти email в рассылку.",
            f"🔒 Запомнено адресов после сброса: <b>{skip_n}</b>.",
            "▶️ <code>/send</code> — только email, добавленные после сброса.",
            "📊 <code>/stat</code> — очередь должна быть <b>0</b>.",
        ]

    await message.answer(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=main_menu_kb(tg_id),
    )
