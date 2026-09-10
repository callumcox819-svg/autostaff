from aiogram.types import InlineKeyboardMarkup, ReplyKeyboardMarkup, ReplyKeyboardRemove

from services.bot_roles import user_is_admin
from utils.ui_emoji import inline_button, label, reply_button

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
    return t in {TEXT_STATUS, label("status", TEXT_STATUS), "📊 Статус рассылки", "/stat", "/status", "/statussend"}


def is_quick_add_trigger(text: str | None) -> bool:
    t = (text or "").strip()
    return t in {
        TEXT_QUICK_ADD,
        label("quick_add", TEXT_QUICK_ADD),
        "⚡ Быстрое добавление",
        "⚡ Быстрое добавление (Gmail)",
        "Быстрое добавление (Gmail)",
    }


def is_admin_trigger(text: str | None) -> bool:
    t = (text or "").strip()
    return t in {
        TEXT_ADMIN,
        label("admin", TEXT_ADMIN),
        "👑 Админ-панель",
        "🔥 Админ-панель",
        "/admin",
    }


def is_test_mail_trigger(text: str | None) -> bool:
    t = (text or "").strip()
    return t in {TEXT_TEST_MAIL, label("test_mail", TEXT_TEST_MAIL), "🧪 Тест маил", "/testmail"}


def hide_reply_keyboard() -> ReplyKeyboardRemove:
    """Убрать залипающую клавиатуру снизу (на телефоне закрывает пол-чата)."""
    return ReplyKeyboardRemove()


def main_menu_kb(user_id: int, *, show_admin: bool = False) -> ReplyKeyboardRemove:
    """Совместимость: больше не рисуем ReplyKeyboard — только снимаем старую."""
    _ = user_id, show_admin
    return hide_reply_keyboard()


def main_menu_inline_kb(user_id: int, *, show_admin: bool = False) -> InlineKeyboardMarkup:
    """Кнопки в сообщении (не перекрывают чат на телефоне)."""
    _ = user_id
    rows = [
        [inline_button("settings", TEXT_SETTINGS, callback_data="menu:settings")],
        [inline_button("quick_add", TEXT_QUICK_ADD, callback_data="menu:quick_add")],
        [
            inline_button("send", TEXT_SEND, callback_data="menu:send"),
            inline_button("stop", TEXT_STOP, callback_data="menu:stop"),
        ],
        [inline_button("status", TEXT_STATUS, callback_data="menu:status")],
        [inline_button("test_mail", TEXT_TEST_MAIL, callback_data="menu:test_mail")],
    ]
    if show_admin:
        rows.append([inline_button("admin", TEXT_ADMIN, callback_data="menu:admin")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def main_menu_kb_for(user_id: int) -> ReplyKeyboardRemove:
    return main_menu_kb(user_id, show_admin=await user_is_admin(user_id))


async def main_menu_inline_kb_for(user_id: int) -> InlineKeyboardMarkup:
    return main_menu_inline_kb(user_id, show_admin=await user_is_admin(user_id))


def legacy_reply_menu_kb(user_id: int, *, show_admin: bool = False) -> ReplyKeyboardMarkup:
    """Старое нижнее меню — только если когда-нибудь понадобится откат."""
    rows = [
        [reply_button("settings", TEXT_SETTINGS)],
        [reply_button("quick_add", TEXT_QUICK_ADD)],
        [
            reply_button("send", TEXT_SEND),
            reply_button("stop", TEXT_STOP),
        ],
        [reply_button("status", TEXT_STATUS)],
        [reply_button("test_mail", TEXT_TEST_MAIL)],
    ]
    if show_admin:
        rows.append([reply_button("admin", TEXT_ADMIN)])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)
