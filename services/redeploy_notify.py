"""Уведомление пользователям после redeploy бота."""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot
from sqlalchemy import or_, select

from database import Session
from models import User

logger = logging.getLogger(__name__)

REDEPLOY_MESSAGE = "бот перезапущен, роси идиот"


async def notify_users_after_redeploy(bot: Bot) -> None:
    """Всем с доступом к боту — один раз при старте bot.py (не imap-worker)."""
    try:
        async with Session() as session:
            tg_ids = [
                int(x)
                for x in (
                    await session.execute(
                        select(User.telegram_id)
                        .where(User.is_banned.is_(False))
                        .where(
                            or_(
                                User.access_granted.is_(True),
                                User.is_admin.is_(True),
                            )
                        )
                    )
                ).scalars().all()
                if x
            ]
    except Exception:
        logger.exception("redeploy_notify: failed to load users")
        return

    if not tg_ids:
        return

    sent = 0
    for tid in tg_ids:
        try:
            await bot.send_message(chat_id=tid, text=REDEPLOY_MESSAGE)
            sent += 1
        except Exception:
            pass
        await asyncio.sleep(0.04)

    logger.info("redeploy_notify: sent to %s/%s users", sent, len(tg_ids))
