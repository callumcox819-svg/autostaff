"""UI: Команды API — список CSM / Evoleum и настройки выбранной команды."""

from __future__ import annotations

import html
import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from database import Session
from services.api_teams import (
    API_TEAMS,
    get_selected_team_id,
    get_team_config,
    link_type_label,
    link_types_for_team,
    set_selected_team_id,
    set_team_field,
    team_label,
)
from services.csm_catalog import (
    country_label,
    list_csm_countries,
    make_service_key,
    parse_service_key,
    platforms_for_country,
    service_key_label,
)
from services.hustle_catalog import (
    hustle_country_label,
    hustle_service_label,
    list_hustle_countries,
    parse_hustle_service,
    platforms_for_hustle_country,
)
from services.users import get_or_create_user
from utils.ui_emoji import (
    back_inline,
    html_emoji,
    icon_button,
    inline_button,
    toast,
    toggle_button,
)

router = Router(name="api_teams")
logger = logging.getLogger(__name__)


class TeamFieldState(StatesGroup):
    waiting = State()


def _teams_list_kb(selected_id: str) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for tid, label in API_TEAMS:
        on = tid == selected_id
        mark = icon_button(
            "ok" if on else "fail",
            callback_data=f"api_team_pick:{tid}",
            style="success" if on else "danger",
        )
        rows.append(
            [
                inline_button(
                    "key"
                    if tid == "csm"
                    else ("pin" if tid == "hustle" else ("burst" if tid == "gag" else "link")),
                    label,
                    callback_data=f"api_team_open:{tid}",
                ),
                mark,
            ]
        )
    rows.append([back_inline("settings_open")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _teams_list_text(selected_id: str, *, page: str = "1/1") -> str:
    return (
        f"{html_emoji('key')} <b>Команды API</b>\n"
        f"Стр. {html.escape(page)}\n\n"
        f"Выбрана: <b>{html.escape(team_label(selected_id))}</b>\n"
        f"{html_emoji('ok')} — активна для генерации · {html_emoji('fail')} — нет"
    )


def _gag_service_toggle_rows(team_id: str, current: str) -> list[list[InlineKeyboardButton]]:
    from services.gag_catalog import GAG_CH_PLATFORMS, normalize_gag_service_code

    cur = normalize_gag_service_code(current)
    row: list[InlineKeyboardButton] = []
    for sid, label, _gen in GAG_CH_PLATFORMS:
        if sid == cur:
            row.append(toggle_button(True, label, f"api_team_gag_svc:{team_id}:{sid}"))
        else:
            row.append(inline_button("compass", label, callback_data=f"api_team_gag_svc:{team_id}:{sid}"))
    return [row] if row else []


def _team_detail_kb(team_id: str, *, service_code: str = "") -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [inline_button("key", "API-ключ", callback_data=f"api_team_edit:{team_id}:api_key")],
    ]
    if team_id == "csm":
        rows.append(
            [
                inline_button(
                    "compass",
                    "Страна / площадка",
                    callback_data=f"api_team_csm_plats:{team_id}",
                )
            ]
        )
    elif team_id == "hustle":
        rows.append(
            [
                inline_button(
                    "compass",
                    "Страна / площадка",
                    callback_data=f"api_team_hustle_plats:{team_id}",
                )
            ]
        )
    elif team_id == "gag":
        rows.extend(_gag_service_toggle_rows(team_id, service_code))
    elif team_id != "gag":
        rows.append(
            [
                inline_button(
                    "wrench",
                    "Код сервиса",
                    callback_data=f"api_team_edit:{team_id}:service_code",
                )
            ]
        )
    if team_id != "gag":
        rows.append(
            [inline_button("profile", "Profile ID", callback_data=f"api_team_edit:{team_id}:profile_id")]
        )
    if team_id == "evoleum":
        rows.extend(
            [
                [
                    inline_button(
                        "user",
                        "ФИО для HTML",
                        callback_data=f"api_team_edit:{team_id}:buyer_name",
                    )
                ],
                [
                    inline_button(
                        "pin",
                        "Адрес для HTML",
                        callback_data=f"api_team_edit:{team_id}:address",
                    )
                ],
            ]
        )
    if team_id in {"hustle", "gag", "csm"}:
        rows.extend(
            [
                [
                    inline_button(
                        "user",
                        "ФИО",
                        callback_data=f"api_team_edit:{team_id}:buyer_name",
                    )
                ],
                [
                    inline_button(
                        "pin",
                        "Адрес",
                        callback_data=f"api_team_edit:{team_id}:address",
                    )
                ],
            ]
        )
    if team_id == "gag":
        rows.append(
            [inline_button("link", "Домен генерации", callback_data="aqua_domain_pick")]
        )
    rows.extend(
        [
            [inline_button("link", "Тип ссылки", callback_data=f"api_team_type_menu:{team_id}")],
            [back_inline("api_teams")],
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _mask_secret(value: str) -> str:
    v = (value or "").strip()
    if not v:
        return "—"
    if len(v) <= 8:
        return "•" * len(v)
    return f"{v[:4]}…{v[-4:]}"


def _team_detail_text(cfg, *, buyer_name: str = "", address: str = "", country_name: str = "") -> str:
    lines = [
        f"{html_emoji('key')} <b>{html.escape(cfg.label)}</b>\n",
        f"<b>API-ключ:</b> <code>{html.escape(_mask_secret(cfg.api_key))}</code>",
    ]
    if cfg.team_id == "csm":
        lines.append(
            f"<b>Площадка:</b> <b>{html.escape(service_key_label(cfg.service_code))}</b>"
            f" (<code>{html.escape(cfg.service_code or '—')}</code>)"
        )
    elif cfg.team_id == "hustle":
        lines.append(
            f"<b>Площадка:</b> <b>{html.escape(hustle_service_label(cfg.service_code))}</b>"
            f" (<code>{html.escape(cfg.service_code or '—')}</code>)"
        )
    elif cfg.team_id == "gag":
        from services.gag_catalog import gag_generate_service, gag_service_label

        lines.append(
            f"<b>Сервис:</b> <b>{html.escape(gag_service_label(cfg.service_code))}</b> "
            f"(<code>{html.escape(cfg.service_code or '—')}</code>)\n"
            f"<b>Генерация ссылки:</b> <code>{html.escape(gag_generate_service(cfg.service_code))}</code>"
        )
    else:
        lines.append(f"<b>Код сервиса:</b> <code>{html.escape(cfg.service_code or '—')}</code>")
    if cfg.team_id != "gag":
        lines.append(f"<b>Profile ID:</b> <code>{html.escape(cfg.profile_id or '—')}</code>")
    if cfg.team_id == "csm":
        cc = f" ({html.escape(country_name)})" if country_name else ""
        lines.append(
            f"<b>ФИО{cc}:</b> <code>{html.escape(buyer_name or '—')}</code>\n"
            f"<b>Адрес{cc}:</b> <code>{html.escape(address or '—')}</code>\n"
            "<i>Только CSM, не Evoleum. На лендинге Meow — Profile ID; "
            "ФИО на карточке в боте — эти поля.</i>"
        )
    if cfg.team_id == "evoleum":
        cc = f" ({html.escape(country_name)})" if country_name else ""
        lines.append(
            f"<b>ФИО для HTML{cc}:</b> <code>{html.escape(buyer_name or '—')}</code>\n"
            f"<b>Адрес для HTML{cc}:</b> <code>{html.escape(address or '—')}</code>\n"
            "<i>Свои на каждую рабочую страну. В HTML-письме — эти поля. "
            "На лендинге Evoleum ФИО/адрес из Profile ID.</i>"
        )
    if cfg.team_id == "hustle":
        cc = f" ({html.escape(country_name)})" if country_name else ""
        lines.append(
            f"<b>ФИО{cc}:</b> <code>{html.escape(buyer_name or '—')}</code>\n"
            f"<b>Адрес{cc}:</b> <code>{html.escape(address or '—')}</code>\n"
            "<i>Те же поля для генерации ссылки и для HTML этой страны. "
            "Team-ключ — только на сервере: <code>HUSTLE_TEAM_KEY</code>.</i>"
        )
    if cfg.team_id == "gag":
        cc = f" ({html.escape(country_name)})" if country_name else ""
        lines.append(
            f"<b>ФИО{cc}:</b> <code>{html.escape(buyer_name or '—')}</code>\n"
            f"<b>Адрес{cc}:</b> <code>{html.escape(address or '—')}</code>\n"
            "<i>Швейцария. Сервис переключается кнопками Ricardo / Markt.ch ниже. "
            "Markt.ch: объявления с markt.ch, ссылка генерируется как <code>posta_ch</code>.</i>"
        )
    lines.append(
        f"<b>Тип ссылки:</b> "
        f"<b>{html.escape(link_type_label(cfg.link_type or 'lk', team_id=cfg.team_id))}</b>"
    )
    return "\n".join(lines)


def _csm_countries_kb(
    team_id: str,
    current_service: str,
    enabled: set[str] | None = None,
) -> InlineKeyboardMarkup:
    """Шаг 1: выбрать страну."""
    from services.enabled_countries import filter_csm_countries, is_country_enabled

    _, cur_cc = parse_service_key(current_service)
    if cur_cc == "verify_all":
        cur_cc = ""
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    countries = filter_csm_countries(enabled)
    if cur_cc and not is_country_enabled(enabled or set(), cur_cc):
        # текущая выбранная — даже если тумблер выкл, чтобы не потерять площадку
        extra = [(cid, label, em) for cid, label, em in list_csm_countries() if cid == cur_cc]
        countries = extra + [c for c in countries if c[0] != cur_cc]
    for cid, label, emoji_key in countries:
        on = cid == cur_cc
        btn = (
            toggle_button(True, label, f"api_team_csm_country:{team_id}:{cid}")
            if on
            else inline_button(
                emoji_key, label, callback_data=f"api_team_csm_country:{team_id}:{cid}"
            )
        )
        row.append(btn)
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([back_inline(f"api_team_open:{team_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _csm_services_kb(team_id: str, country: str, current_service: str) -> InlineKeyboardMarkup:
    """Шаг 2: сервисы выбранной страны + Verify."""
    cur_plat, cur_cc = parse_service_key(current_service)
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for pid, label, emoji_key in platforms_for_country(country):
        on = cur_plat == pid and cur_cc == country
        btn = (
            toggle_button(True, label, f"api_team_csm_svc:{team_id}:{country}:{pid}")
            if on
            else inline_button(
                emoji_key, label, callback_data=f"api_team_csm_svc:{team_id}:{country}:{pid}"
            )
        )
        row.append(btn)
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)

    # Verify по каждому сервису страны — компактно одной кнопкой на primary
    primary = platforms_for_country(country)[0][0]
    on_v = cur_plat == primary and cur_cc == "verify_all"
    rows.append(
        [
            toggle_button(
                True, "Verify", f"api_team_csm_svc:{team_id}:{country}:{primary}:verify"
            )
            if on_v
            else inline_button(
                "ok",
                "Verify",
                callback_data=f"api_team_csm_svc:{team_id}:{country}:{primary}:verify",
            )
        ]
    )
    rows.append([back_inline(f"api_team_csm_plats:{team_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _link_type_kb(team_id: str, current: str) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for tid, label, emoji_key in link_types_for_team(team_id):
        on = tid == current
        caption = f"{label}" + (" ✓" if on else "")
        if on:
            rows.append([toggle_button(True, caption, f"api_team_type:{team_id}:{tid}")])
        else:
            rows.append(
                [inline_button(emoji_key, caption, callback_data=f"api_team_type:{team_id}:{tid}")]
            )
    rows.append([back_inline(f"api_team_open:{team_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _link_type_text(team_id: str, current: str) -> str:
    return (
        f"{html_emoji('link')} <b>Тип ссылки</b>\n"
        f"Команда: <b>{html.escape(team_label(team_id))}</b>\n\n"
        f"Какая ссылка будет генерироваться:\n"
        f"сейчас — <b>{html.escape(link_type_label(current, team_id=team_id))}</b>"
    )


async def _edit(callback: CallbackQuery, text: str, kb: InlineKeyboardMarkup) -> None:
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except TelegramBadRequest:
        try:
            await callback.message.answer(text, reply_markup=kb, parse_mode="HTML")
        except Exception:
            pass


@router.callback_query(F.data == "api_teams")
async def api_teams_menu(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    async with Session() as session:
        user = await get_or_create_user(session, callback.from_user.id)
        selected = await get_selected_team_id(session, user)
    await _edit(callback, _teams_list_text(selected), _teams_list_kb(selected))
    await callback.answer()


@router.callback_query(F.data.startswith("api_team_pick:"))
async def api_team_pick(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    tid = (callback.data or "").split(":", 1)[-1].strip()
    async with Session() as session:
        user = await get_or_create_user(session, callback.from_user.id)
        try:
            selected = await set_selected_team_id(session, user, tid)
            from services.api_teams import get_team_config
            from services.aqua_keys import sync_html_service_from_code

            cfg = await get_team_config(session, user, selected)
            await sync_html_service_from_code(session, user, cfg.service_code)
            await session.commit()
        except ValueError:
            await callback.answer(toast("fail", "Неизвестная команда"), show_alert=True)
            return
    await _edit(callback, _teams_list_text(selected), _teams_list_kb(selected))
    await callback.answer(toast("ok", f"Выбрано: {team_label(selected)}"))


async def _evoleum_html_profile_fields(session, user) -> tuple[str, str]:
    from services.aqua_keys import get_user_profile_address, get_user_profile_buyer_name

    return (
        await get_user_profile_buyer_name(session, user),
        await get_user_profile_address(session, user),
    )


async def _team_detail_payload(session, user, tid: str) -> tuple[object, str]:
    from services.country_scope import country_display_name
    from services.enabled_countries import get_active_country

    cfg = await get_team_config(session, user, tid)
    buyer = addr = ""
    cc_name = country_display_name(await get_active_country(session, user))
    if cfg.team_id == "evoleum":
        buyer, addr = await _evoleum_html_profile_fields(session, user)
    elif cfg.team_id in {"hustle", "gag", "csm"}:
        from services.api_teams import get_team_field

        buyer = await get_team_field(session, user, cfg.team_id, "buyer_name")
        addr = await get_team_field(session, user, cfg.team_id, "address")
    return cfg, _team_detail_text(cfg, buyer_name=buyer, address=addr, country_name=cc_name)


@router.callback_query(F.data.startswith("api_team_open:"))
async def api_team_open(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    tid = (callback.data or "").split(":", 1)[-1].strip()
    async with Session() as session:
        user = await get_or_create_user(session, callback.from_user.id)
        try:
            cfg, text = await _team_detail_payload(session, user, tid)
        except Exception:
            await callback.answer(toast("fail", "Ошибка"), show_alert=True)
            return
    if cfg.team_id not in {t for t, _ in API_TEAMS}:
        await callback.answer(toast("fail", "Неизвестная команда"), show_alert=True)
        return
    await _edit(callback, text, _team_detail_kb(cfg.team_id, service_code=cfg.service_code))
    await callback.answer()


@router.callback_query(F.data.startswith("api_team_csm_plats:"))
async def api_team_csm_plats(callback: CallbackQuery, state: FSMContext) -> None:
    """Шаг 1 — список стран."""
    await state.clear()
    tid = (callback.data or "").split(":", 1)[-1].strip()
    async with Session() as session:
        user = await get_or_create_user(session, callback.from_user.id)
        cfg = await get_team_config(session, user, tid)
        from services.enabled_countries import get_enabled_country_ids

        enabled = await get_enabled_country_ids(session, user)
    text = (
        f"{html_emoji('compass')} <b>Страна CSM</b>\n"
        f"Сейчас: <b>{html.escape(service_key_label(cfg.service_code))}</b>\n\n"
        f"Выбери страну:"
    )
    await _edit(callback, text, _csm_countries_kb(tid, cfg.service_code or "marktplaats_nl", enabled))
    await callback.answer()


@router.callback_query(F.data.startswith("api_team_csm_country:"))
async def api_team_csm_country(callback: CallbackQuery, state: FSMContext) -> None:
    """Шаг 2 — сервисы выбранной страны."""
    await state.clear()
    parts = (callback.data or "").split(":")
    if len(parts) != 3:
        await callback.answer()
        return
    _, tid, country = parts
    async with Session() as session:
        user = await get_or_create_user(session, callback.from_user.id)
        cfg = await get_team_config(session, user, tid)
    text = (
        f"{html_emoji('compass')} <b>{html.escape(country_label(country))}</b>\n"
        f"Сейчас: <b>{html.escape(service_key_label(cfg.service_code))}</b>\n\n"
        f"Выбери сервис:"
    )
    await _edit(
        callback,
        text,
        _csm_services_kb(tid, country, cfg.service_code or make_service_key("depop", country)),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("api_team_csm_svc:"))
async def api_team_csm_svc(callback: CallbackQuery, state: FSMContext) -> None:
    """Сохранить serviceKey = platform_country | platform_verify_all."""
    await state.clear()
    parts = (callback.data or "").split(":")
    # api_team_csm_svc:tid:country:platform[:verify]
    if len(parts) < 4:
        await callback.answer()
        return
    tid = parts[1]
    country = parts[2]
    platform = parts[3]
    verify = len(parts) >= 5 and parts[4] == "verify"
    sk = make_service_key(platform, "verify_all" if verify else country)
    async with Session() as session:
        user = await get_or_create_user(session, callback.from_user.id)
        try:
            await set_team_field(session, user, tid, "service_code", sk)
            from services.aqua_keys import sync_html_service_from_code

            await sync_html_service_from_code(session, user, sk)
            await session.commit()
            cfg = await get_team_config(session, user, tid)
        except ValueError as e:
            await callback.answer(toast("fail", str(e)[:180]), show_alert=True)
            return
    await _edit(callback, _team_detail_text(cfg), _team_detail_kb(tid, service_code=cfg.service_code))
    await callback.answer(toast("ok", service_key_label(sk)))


# Совместимость со старыми callback (платформа → страна)
@router.callback_query(F.data.startswith("api_team_csm_plat:"))
async def api_team_csm_plat_legacy(callback: CallbackQuery, state: FSMContext) -> None:
    tid = (callback.data or "").split(":")[1] if ":" in (callback.data or "") else "csm"
    callback.data = f"api_team_csm_plats:{tid}"
    return await api_team_csm_plats(callback, state)


@router.callback_query(F.data.startswith("api_team_csm_cc:"))
async def api_team_csm_cc_legacy(callback: CallbackQuery, state: FSMContext) -> None:
    parts = (callback.data or "").split(":")
    if len(parts) >= 4:
        tid, platform, country = parts[1], parts[2], parts[3]
        callback.data = f"api_team_csm_svc:{tid}:{country}:{platform}"
        if country in {"verify_all", "verify"}:
            # старый формат: platform + verify
            callback.data = f"api_team_csm_svc:{tid}:us:{platform}:verify"
        return await api_team_csm_svc(callback, state)
    await callback.answer()


def _hustle_countries_kb(
    team_id: str,
    current_service: str,
    enabled: set[str] | None = None,
) -> InlineKeyboardMarkup:
    from services.enabled_countries import is_country_enabled

    _, cur_cc = parse_hustle_service(current_service)
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for cid, label, emoji_key in list_hustle_countries():
        if enabled is not None and not is_country_enabled(enabled, cid) and cid != cur_cc:
            continue
        on = cid == cur_cc
        btn = (
            toggle_button(True, label, f"api_team_hustle_country:{team_id}:{cid}")
            if on
            else inline_button(
                emoji_key, label, callback_data=f"api_team_hustle_country:{team_id}:{cid}"
            )
        )
        row.append(btn)
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([back_inline(f"api_team_open:{team_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _hustle_services_kb(team_id: str, country: str, current_service: str) -> InlineKeyboardMarkup:
    cur, _cc = parse_hustle_service(current_service)
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for sid, label, emoji_key, _mode in platforms_for_hustle_country(country):
        on = sid == cur
        btn = (
            toggle_button(True, label, f"api_team_hustle_svc:{team_id}:{sid}")
            if on
            else inline_button(
                emoji_key, label, callback_data=f"api_team_hustle_svc:{team_id}:{sid}"
            )
        )
        row.append(btn)
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([back_inline(f"api_team_hustle_plats:{team_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(F.data.startswith("api_team_hustle_plats:"))
async def api_team_hustle_plats(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    tid = (callback.data or "").split(":", 1)[-1].strip()
    async with Session() as session:
        user = await get_or_create_user(session, callback.from_user.id)
        cfg = await get_team_config(session, user, tid)
        from services.enabled_countries import get_enabled_country_ids

        enabled = await get_enabled_country_ids(session, user)
    text = (
        f"{html_emoji('compass')} <b>Страна Hustle Castle</b>\n"
        f"Сейчас: <b>{html.escape(hustle_service_label(cfg.service_code))}</b>\n\n"
        f"Выбери страну:"
    )
    await _edit(
        callback,
        text,
        _hustle_countries_kb(tid, cfg.service_code or "kleinanzeigen_de", enabled),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("api_team_hustle_country:"))
async def api_team_hustle_country(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    parts = (callback.data or "").split(":")
    if len(parts) != 3:
        await callback.answer()
        return
    _, tid, country = parts
    async with Session() as session:
        user = await get_or_create_user(session, callback.from_user.id)
        cfg = await get_team_config(session, user, tid)
    text = (
        f"{html_emoji('compass')} <b>{html.escape(hustle_country_label(country))}</b>\n"
        f"Сейчас: <b>{html.escape(hustle_service_label(cfg.service_code))}</b>\n\n"
        f"Выбери сервис:"
    )
    await _edit(
        callback,
        text,
        _hustle_services_kb(tid, country, cfg.service_code or "kleinanzeigen_de"),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("api_team_hustle_svc:"))
async def api_team_hustle_svc(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    parts = (callback.data or "").split(":")
    if len(parts) < 3:
        await callback.answer()
        return
    tid = parts[1]
    sk = parts[2]
    async with Session() as session:
        user = await get_or_create_user(session, callback.from_user.id)
        try:
            await set_team_field(session, user, tid, "service_code", sk)
            from services.aqua_keys import sync_html_service_from_code

            await sync_html_service_from_code(session, user, sk)
            await session.commit()
            cfg, text = await _team_detail_payload(session, user, tid)
        except ValueError as e:
            await callback.answer(toast("fail", str(e)[:180]), show_alert=True)
            return
    await _edit(callback, text, _team_detail_kb(tid, service_code=cfg.service_code))
    await callback.answer(toast("ok", hustle_service_label(sk)))


def _gag_plats_kb(team_id: str, current: str) -> InlineKeyboardMarkup:
    from services.gag_catalog import GAG_CH_PLATFORMS, normalize_gag_service_code

    cur = normalize_gag_service_code(current)
    rows: list[list[InlineKeyboardButton]] = []
    for sid, label, gen in GAG_CH_PLATFORMS:
        title = label if gen == sid else f"{label} → {gen}"
        if sid == cur:
            rows.append([toggle_button(True, title, f"api_team_gag_svc:{team_id}:{sid}")])
        else:
            rows.append(
                [inline_button("compass", title, callback_data=f"api_team_gag_svc:{team_id}:{sid}")]
            )
    rows.append([back_inline(f"api_team_open:{team_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(F.data.startswith("api_team_gag_plats:"))
async def api_team_gag_plats(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    tid = (callback.data or "").split(":", 1)[-1].strip()
    async with Session() as session:
        user = await get_or_create_user(session, callback.from_user.id)
        cfg = await get_team_config(session, user, tid)
    from services.gag_catalog import gag_generate_service, gag_service_label

    text = (
        f"{html_emoji('compass')} <b>Площадка GAG (Швейцария)</b>\n\n"
        f"Сейчас: <b>{html.escape(gag_service_label(cfg.service_code))}</b> "
        f"(<code>{html.escape(cfg.service_code or '—')}</code>)\n"
        f"В API уйдёт: <code>{html.escape(gag_generate_service(cfg.service_code))}</code>\n\n"
        "Markt.ch — объявления с markt.ch, генерация ссылки через <code>posta_ch</code>."
    )
    await _edit(callback, text, _gag_plats_kb(tid, cfg.service_code))
    await callback.answer()


@router.callback_query(F.data.startswith("api_team_gag_svc:"))
async def api_team_gag_svc(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    parts = (callback.data or "").split(":")
    if len(parts) < 3:
        await callback.answer()
        return
    tid = parts[1]
    sk = parts[2]
    async with Session() as session:
        user = await get_or_create_user(session, callback.from_user.id)
        try:
            await set_team_field(session, user, tid, "service_code", sk)
            from services.aqua_keys import sync_html_service_from_code

            await sync_html_service_from_code(session, user, sk)
            await session.commit()
            cfg, text = await _team_detail_payload(session, user, tid)
        except ValueError as e:
            await callback.answer(toast("fail", str(e)[:180]), show_alert=True)
            return
    from services.gag_catalog import gag_service_label

    await _edit(callback, text, _team_detail_kb(tid, service_code=cfg.service_code))
    await callback.answer(toast("ok", gag_service_label(sk)))


_FIELD_TITLES = {
    "api_key": "API-ключ",
    "service_code": "Код сервиса",
    "profile_id": "Profile ID",
    "buyer_name": "ФИО для HTML",
    "address": "Адрес для HTML",
}


@router.callback_query(F.data.startswith("api_team_type_menu:"))
async def api_team_type_menu(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    tid = (callback.data or "").split(":", 1)[-1].strip()
    async with Session() as session:
        user = await get_or_create_user(session, callback.from_user.id)
        cfg = await get_team_config(session, user, tid)
    if cfg.team_id not in {t for t, _ in API_TEAMS}:
        await callback.answer(toast("fail", "Неизвестная команда"), show_alert=True)
        return
    cur = cfg.link_type or "lk"
    await _edit(callback, _link_type_text(tid, cur), _link_type_kb(tid, cur))
    await callback.answer()


@router.callback_query(F.data.startswith("api_team_type:"))
async def api_team_type_set(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    parts = (callback.data or "").split(":")
    if len(parts) != 3:
        await callback.answer()
        return
    _, tid, link_type = parts
    async with Session() as session:
        user = await get_or_create_user(session, callback.from_user.id)
        try:
            await set_team_field(session, user, tid, "link_type", link_type)
            await session.commit()
            cfg = await get_team_config(session, user, tid)
        except ValueError as e:
            await callback.answer(toast("fail", str(e)[:180]), show_alert=True)
            return
    cur = cfg.link_type or "lk"
    await _edit(callback, _link_type_text(tid, cur), _link_type_kb(tid, cur))
    await callback.answer(toast("ok", f"Тип: {link_type_label(cur, team_id=tid)}"))


@router.callback_query(F.data.startswith("api_team_edit:"))
async def api_team_edit(callback: CallbackQuery, state: FSMContext) -> None:
    parts = (callback.data or "").split(":")
    if len(parts) != 3:
        await callback.answer()
        return
    _, tid, field = parts
    if field == "link_type":
        callback.data = f"api_team_type_menu:{tid}"
        return await api_team_type_menu(callback, state)
    if field == "service_code" and tid == "csm":
        callback.data = f"api_team_csm_plats:{tid}"
        return await api_team_csm_plats(callback, state)
    if field == "service_code" and tid == "hustle":
        callback.data = f"api_team_hustle_plats:{tid}"
        return await api_team_hustle_plats(callback, state)
    if field == "service_code" and tid == "gag":
        callback.data = f"api_team_gag_plats:{tid}"
        return await api_team_gag_plats(callback, state)
    if field not in _FIELD_TITLES:
        await callback.answer(toast("fail", "Поле"), show_alert=True)
        return
    await state.set_state(TeamFieldState.waiting)
    await state.update_data(team_id=tid, field=field)
    hint = ""
    if field == "service_code" and tid == "evoleum":
        hint = "\nДля NL обычно: <code>marktplaats_nl</code>."
    if field == "profile_id" and tid == "evoleum":
        hint = (
            "\n\nФИО и адрес на <b>ссылке</b> берутся из этого профиля в Evoleum.\n"
            "После сохранения обязательно заполни <b>ФИО для HTML</b> и <b>Адрес для HTML</b> "
            "теми же данными — GOO API не отдаёт их в письмо."
        )
    if field == "buyer_name" and tid == "evoleum":
        hint = "\n\nКак в профиле Evoleum (например: <code>Maria Zeglier</code>)."
    if field == "address" and tid == "evoleum":
        hint = "\n\nКак в профиле Evoleum (улица, индекс, город, NL)."
    if field == "profile_id" and tid == "hustle":
        hint = "\nИз бота Hustle Castle: Настройки › Профили. Нужен для FAST (Kleinanzeigen с ссылкой)."
    if field == "buyer_name" and tid == "hustle":
        hint = "\nФИО покупателя для генерации (lonely / eBay)."
    if field == "address" and tid == "hustle":
        hint = "\nАдрес в Германии, например: <code>Berliner Straße 115, 63272 Frankfurt</code>."
    if field == "service_code" and tid == "gag":
        callback.data = f"api_team_gag_plats:{tid}"
        return await api_team_gag_plats(callback, state)
    if field == "buyer_name" and tid == "gag":
        hint = "\nФИО получателя в теле /generate."
    if field == "address" and tid == "gag":
        hint = "\nАдрес доставки в теле /generate."
    await _edit(
        callback,
        f"{html_emoji('settings')} <b>{html.escape(_FIELD_TITLES[field])}</b>\n"
        f"Команда: <b>{html.escape(team_label(tid))}</b>\n\n"
        f"Пришли новое значение одним сообщением.{hint}",
        InlineKeyboardMarkup(
            inline_keyboard=[[back_inline(f"api_team_open:{tid}", text="Отмена")]]
        ),
    )
    await callback.answer()


@router.message(TeamFieldState.waiting)
async def api_team_field_save(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    tid = str(data.get("team_id") or "")
    field = str(data.get("field") or "")
    raw = (message.text or "").strip()
    if not tid or not field:
        await state.clear()
        return
    if field == "team_key":
        await state.clear()
        await message.answer(
            f"{html_emoji('fail')} Team-ключ задаётся только на сервере, не в боте.",
            parse_mode="HTML",
        )
        return
    async with Session() as session:
        user = await get_or_create_user(session, message.from_user.id)
        try:
            if tid == "evoleum" and field in {"buyer_name", "address"}:
                from services.aqua_keys import (
                    AQUA_PROFILE_ADDRESS_KEY,
                    AQUA_PROFILE_NAME_KEY,
                    get_user_goo_profile_id,
                )
                from services.country_scope import set_scoped_setting

                key = (
                    AQUA_PROFILE_NAME_KEY
                    if field == "buyer_name"
                    else AQUA_PROFILE_ADDRESS_KEY
                )
                await set_scoped_setting(session, user, key, raw)
                cfg = await get_team_config(session, user, tid)
                # Привязка к текущему Profile ID, чтобы HTML не считал ФИО «чужим».
                if (cfg.profile_id or "").strip():
                    user.goo_profile_id = (cfg.profile_id or "").strip()
                elif not get_user_goo_profile_id(user) and (cfg.profile_id or "").strip():
                    user.goo_profile_id = cfg.profile_id
            else:
                await set_team_field(session, user, tid, field, raw)
                if field == "service_code":
                    from services.aqua_keys import sync_html_service_from_code

                    await sync_html_service_from_code(session, user, raw)
            await session.commit()
            cfg, detail = await _team_detail_payload(session, user, tid)
        except ValueError as e:
            await message.answer(f"{html_emoji('fail')} {html.escape(str(e))}", parse_mode="HTML")
            return
    await state.clear()
    extra = ""
    if tid == "evoleum" and field == "profile_id":
        extra = (
            f"\n\n{html_emoji('wait')} Теперь укажи <b>ФИО для HTML</b> и <b>Адрес для HTML</b> "
            "как в этом профиле Evoleum."
        )
    await message.answer(
        f"{html_emoji('ok')} Сохранено.{extra}\n\n{detail}",
        reply_markup=_team_detail_kb(tid, service_code=cfg.service_code),
        parse_mode="HTML",
    )
