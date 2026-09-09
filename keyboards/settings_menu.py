from aiogram.types import InlineKeyboardMarkup

from utils.ui_emoji import inline_button


def settings_back_kb() -> InlineKeyboardMarkup:
    """Назад в главное меню настроек."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [inline_button("back", "Назад", callback_data="settings_open")],
        ]
    )
