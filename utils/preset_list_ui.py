"""Общий экран списка текстовых пресетов (копируемые <code>, кнопки как в боте)."""

from __future__ import annotations

from html import escape
from typing import List

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from utils.ui_emoji import back_inline, inline_button, html_emoji

FOOTER_VARIABLES = "<b>Переменная:</b> <code>OFFER</code> / <code>{{OFFER}}</code>"
FOOTER_SPINTAX = "<b>Спинтаксис:</b> <code>{a|b|c}</code>"

NOTE_SMART_PRESETS = (
    "<i>При рассылке используются тексты отсюда. Обычные пресеты — только если этот список пуст.</i>"
)
NOTE_REGULAR_PRESETS = (
    "<i>Название — на кнопках при быстром ответе на письмо. Текст — уходит получателю.</i>"
)

REGULAR_PRESETS_EMPTY_HINT = (
    "Пока нет пресетов.\n"
    "Нажми «Добавить пресет»: сначала имя для кнопки, затем текст письма."
)

TEXT_PRESETS_PAGE_SIZE = 20


def preset_page_count(total_items: int, page_size: int = TEXT_PRESETS_PAGE_SIZE) -> int:
    if total_items <= 0:
        return 1
    return (total_items + page_size - 1) // page_size


def clamp_preset_page(page: int, total_items: int, page_size: int = TEXT_PRESETS_PAGE_SIZE) -> int:
    pages = preset_page_count(total_items, page_size)
    p = max(0, int(page))
    return min(p, pages - 1)


def preset_last_page(total_items: int, page_size: int = TEXT_PRESETS_PAGE_SIZE) -> int:
    if total_items <= 0:
        return 0
    return (total_items - 1) // page_size


def render_text_presets_page(
    header_html: str,
    texts: List[str],
    *,
    empty_hint: str | None = None,
    footer_note: str | None = None,
    max_show: int = 40,
    page: int = 0,
    page_size: int | None = None,
) -> str:
    if not texts:
        hint = empty_hint or (
            "Пока нет пресетов.\n"
            f"Нажми «{html_emoji('add')} Добавить пресет» и отправь текст одним сообщением."
        )
        return f"{header_html}\n\n{hint}\n\n{FOOTER_VARIABLES}\n{FOOTER_SPINTAX}"

    psz = int(page_size if page_size is not None else max_show)
    total = len(texts)
    pg = clamp_preset_page(page, total, psz)
    pages = preset_page_count(total, psz)
    start = pg * psz
    chunk = texts[start : start + psz]
    preview_len = 220 if psz <= TEXT_PRESETS_PAGE_SIZE else 500

    lines: List[str] = [header_html, ""]
    for i, raw in enumerate(chunk, start=start + 1):
        txt = escape((raw or "").strip().replace("\n", " "))
        if len(txt) > preview_len:
            txt = txt[: preview_len - 1] + "…"
        lines.append(f"<b>Пресет #{i}</b>\n<code>{txt}</code>\n")
    if pages > 1:
        lines.append(f"<i>Страница {pg + 1} / {pages} · всего {total}</i>")
    elif total > len(chunk):
        lines.append(f"…и ещё {total - len(chunk)}")
    lines.append("")
    lines.append(FOOTER_VARIABLES)
    lines.append(FOOTER_SPINTAX)
    if footer_note:
        lines.append(footer_note)
    return "\n".join(lines)


def with_text_presets_pagination(
    kb: InlineKeyboardMarkup,
    *,
    page: int,
    total_items: int,
    page_cb_prefix: str,
    page_size: int = TEXT_PRESETS_PAGE_SIZE,
) -> InlineKeyboardMarkup:
    pages = preset_page_count(total_items, page_size)
    if pages <= 1:
        return kb
    pg = clamp_preset_page(page, total_items, page_size)
    nav: List[InlineKeyboardButton] = []
    if pg > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"{page_cb_prefix}:{pg - 1}"))
    else:
        nav.append(InlineKeyboardButton(text=" ", callback_data=f"{page_cb_prefix}:noop"))
    nav.append(InlineKeyboardButton(text=f"{pg + 1} / {pages}", callback_data=f"{page_cb_prefix}:noop"))
    if pg < pages - 1:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"{page_cb_prefix}:{pg + 1}"))
    else:
        nav.append(InlineKeyboardButton(text=" ", callback_data=f"{page_cb_prefix}:noop"))
    rows = [list(r) for r in kb.inline_keyboard]
    rows.insert(-1, nav)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def text_presets_manage_kb(
    *,
    add_cb: str,
    edit_cb: str,
    del_cb: str,
    del_all_cb: str,
    back_cb: str,
    hide_cb: str,
    has_any: bool,
    add_txt_cb: str | None = None,
) -> InlineKeyboardMarkup:
    rows: List[List[InlineKeyboardButton]] = [
        [
            inline_button("add", "Добавить пресет", callback_data=add_cb),
        ],
    ]
    if add_txt_cb:
        rows[0].append(
            inline_button("add", "Заменить из .txt", callback_data=add_txt_cb),
        )
    rows.append(
        [
            inline_button("edit", "Изменить пресет", callback_data=edit_cb),
        ]
    )
    if has_any:
        rows.append(
            [
                inline_button("delete", "Удалить пресет", callback_data=del_cb),
                inline_button("delete", "Удалить все", callback_data=del_all_cb),
            ]
        )
    rows.append(
        [
            back_inline(back_cb),
            inline_button("hide", "Скрыть", callback_data=hide_cb),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def render_named_presets_page(
    header_html: str,
    items: list[tuple[str, str]],
    *,
    empty_hint: str | None = None,
    footer_note: str | None = None,
    max_show: int = 40,
) -> str:
    """Пресеты с названием (ответы на письма): название + текст в списке."""
    if not items:
        hint = empty_hint or REGULAR_PRESETS_EMPTY_HINT
        out = f"{header_html}\n\n{hint}"
        if footer_note:
            out += f"\n\n{footer_note}"
        return out

    lines: List[str] = [header_html, ""]
    for i, (title, body) in enumerate(items[:max_show], start=1):
        name = escape((title or "").strip())
        txt = escape((body or "").strip().replace("\n", " "))
        if len(txt) > 500:
            txt = txt[:497] + "…"
        lines.append(f"<b>Пресет #{i}</b> · <u>{name}</u>\n<code>{txt}</code>\n")
    if len(items) > max_show:
        lines.append(f"…и ещё {len(items) - max_show}")
    if footer_note:
        lines.append(f"\n{footer_note}")
    return "\n".join(lines)


def named_presets_pick_kb(
    items: list[tuple[str, str]],
    action: str,
    back_cb: str,
) -> InlineKeyboardMarkup:
    rows: List[List[InlineKeyboardButton]] = []
    for i, (title, _) in enumerate(items[:40]):
        label = (title or f"Пресет #{i + 1}").strip()[:40]
        rows.append([InlineKeyboardButton(text=label, callback_data=f"{action}:{i}")])
    rows.append([back_inline(back_cb)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def text_presets_pick_kb(count: int, action: str, back_cb: str) -> InlineKeyboardMarkup:
    rows: List[List[InlineKeyboardButton]] = []
    for i in range(min(count, 40)):
        rows.append([InlineKeyboardButton(text=f"Пресет #{i + 1}", callback_data=f"{action}:{i}")])
    rows.append([back_inline(back_cb)])
    return InlineKeyboardMarkup(inline_keyboard=rows)
