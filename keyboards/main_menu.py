from aiogram.types import ReplyKeyboardMarkup

from services.bot_roles import user_is_admin
from utils.ui_emoji import label, reply_button

TEXT_SETTINGS = "Настройки"
TEXT_QUICK_ADD = "Быстрое добавление"
TEXT_SEND = "Запустить рассылку"
TEXT_STOP = "Остановить рассылку"
TEXT_STATUS = "Статус рассылки"
TEXT_ADMIN = "Админ-панель"
TEXT_TEST_MAIL = "Тест маил"


def _menu_text_variants(*keys_and_plain: tuple[str, str]) -> frozenset[str]:
    out: set[str] = set()
    for key, plain in keys_and_plain:
        out.add(plain)
        out.add(label(key, plain))
        # legacy unicode labels
        legacy = {
            TEXT_SETTINGS: ("⚙️ Настройки", "Настройки"),
            TEXT_QUICK_ADD: ("⚡ Быстрое добавление", "⚡ Быстрое добавление (Gmail)"),
            TEXT_SEND: ("▶️ Запустить рассылку",),
            TEXT_STOP: ("⏹ Остановить рассылку", "/stop", "/stopsend"),
            TEXT_STATUS: ("📊 Статус рассылки",),
            TEXT_ADMIN: ("👑 Админ-панель", "🔥 Админ-панель"),
            TEXT_TEST_MAIL: ("🧪 Тест маил",),
        }
        out.update(legacy.get(plain, ()))
    return frozenset(out)


MAIN_MENU_TEXTS = _menu_text_variants(
    ("settings", TEXT_SETTINGS),
    ("quick_add", TEXT_QUICK_ADD),
    ("send", TEXT_SEND),
    ("stop", TEXT_STOP),
    ("status", TEXT_STATUS),
    ("admin", TEXT_ADMIN),
    ("test_mail", TEXT_TEST_MAIL),
)


def is_main_menu_text(text: str | None) -> bool:
    t = (text or "").strip()
    if t in MAIN_MENU_TEXTS:
        return True
    tl = t.casefold().replace("\ufe0f", "")
    return "настройки" in tl


def is_send_trigger(text: str | None) -> bool:
    t = (text or "").strip()
    return t in {TEXT_SEND, label("send", TEXT_SEND), "▶️ Запустить рассылку", "/send"}


def is_stop_trigger(text: str | None) -> bool:
    t = (text or "").strip()
    return t in {TEXT_STOP, label("stop", TEXT_STOP), "⏹ Остановить рассылку", "/stop", "/stopsend"}


def is_status_trigger(text: str | None) -> bool:
    t = (text or "").strip()
    return t in {TEXT_STATUS, label("status", TEXT_STATUS), "📊 Статус рассылки", "/stat"}


def main_menu_kb(user_id: int, *, show_admin: bool = False) -> ReplyKeyboardMarkup:
    rows = [
        [reply_button("settings", TEXT_SETTINGS)],
        [reply_button("quick_add", TEXT_QUICK_ADD)],
        [
            reply_button("send", TEXT_SEND),
            reply_button("stop", TEXT_STOP),
        ],
        [reply_button("status", TEXT_STATUS)],
    ]

    if show_admin:
        rows.append([reply_button("admin", TEXT_ADMIN)])
        rows.append([reply_button("test_mail", TEXT_TEST_MAIL)])

    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


async def main_menu_kb_for(user_id: int) -> ReplyKeyboardMarkup:
    return main_menu_kb(user_id, show_admin=await user_is_admin(user_id))
