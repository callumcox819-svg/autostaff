import json
import logging
import os
import tempfile
import time
import asyncio
import re
from typing import Any, Dict, List

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, FSInputFile

from sqlalchemy import select

from database import db_session
from models import Offer, OfferEmail, Domain
from services.users import get_or_create_user
from config import config
from services.validemail_keys import (
    per_key_concurrency_limit,
    resolve_validemail_api_keys,
    validation_pool_size,
)
from services.validemail_validator import (
    ValidationConfig,
    merge_validation_domains,
    validate_offers,
)
from services.offer_storage import save_all_offers_from_import, format_validated_export_document
from services.seller_name import (
    seller_name_eligible_for_validation,
    seller_name_from_item,
    seller_name_min_letters,
)
from services.sending_state import get_sending_state, set_sending_state
from services.mailing_active_db import is_user_mailing_active
from utils.bg_jobs import (
    cancel as bg_cancel,
    is_running as bg_is_running,
    running_since as bg_running_since,
    start as bg_start,
)
from utils.ui_emoji import html_emoji, inline_button, menu_path, toast, msg_fail, msg_ok, msg_wait, msg_warn

router = Router()

logger = logging.getLogger(__name__)

REPLACE_OLD_FOR_USER = False
REQUIRE_FIRST_AND_LAST = False
PROGRESS_UPDATE_INTERVAL = 3  # seconds
# Одна валидная почта на продавца → один OfferEmail, без путаницы при AQUA и входящих.
MAX_EMAILS_PER_SELLER = 1
MAX_EMAILS_PER_OFFER = 1

# Снимок прогресса текущего подбора (для сообщения «уже идёт»)
_validation_snapshots: dict[int, dict[str, Any]] = {}


def _running_validation_hint(tg_id: int) -> str:
    snap = _validation_snapshots.get(int(tg_id)) or {}
    total = int(snap.get("offers_total") or 0)
    si = int(snap.get("seller_index") or 0)
    since = bg_running_since(tg_id, "validation")
    mins = ""
    if since:
        mins = f" · уже <b>{max(0, int((time.time() - since) // 60))}</b> мин"
    prog = f" · продавцы <b>{si}/{total}</b>" if total else ""
    return (
        f"{html_emoji('wait')} <b>Предыдущий подбор email ещё идёт</b>{mins}{prog}.\n\n"
        f"Этот JSON <b>не запущен</b> — смотри прогресс в сообщении <b>выше</b> в чате.\n"
        f"Остановить: <code>/stopvalid</code>, затем пришли файл снова."
    )


def _progress_bar(done: int, total: int, width: int = 20) -> tuple[str, int]:
    if total <= 0:
        return "░" * width, 0
    pct = int((done / total) * 100)
    filled = max(0, min(width, int((done / total) * width)))
    return ("█" * filled + "░" * (width - filled)), pct


def _validation_user_line(message: Message) -> str:
    u = message.from_user
    if not u:
        return ""
    un = f"@{u.username}" if u.username else ""
    return f"{html_emoji('profile')} <code>{u.id}</code> {un}".strip()


def _format_validation_status(
    *,
    finished: bool,
    user_line: str,
    processed: int,
    total: int,
    added: int,
    duplicates: int,
    in_blacklist: int,
    added_blacklist: int,
    short_nicks: int,
    no_email: int,
    errors: int,
    sellers_api_unresolved: int = 0,
    no_email_smtp: int = 0,
    validemail_keys: int = 0,
    validemail_pool: int = 0,
    validemail_per_key: int = 0,
    validemail_threads: int = 0,
    phase: str = "",
    sellers_total: int = 0,
    seller_index: int = 0,
    validemail_domains: int = 0,
    validemail_max_locals: int = 0,
    validemail_api_timeout: int = 0,
    traffic_mode: bool = False,
    priority_domains: list[str] | None = None,
    current_domain: str = "",
    validation_t0: float = 0,
    seller_parallel_cap: int = 0,
    api_retry_queued: int = 0,
    api_retry_done: int = 0,
    seller_timeouts: int = 0,
    offers_eligible: int = 0,
    listings_in_file: int = 0,
    no_name: int = 0,
    already_in_db: int = 0,
) -> str:
    title = (
        f"{html_emoji('ok')} Подбор завершён"
        if finished
        else f"{html_emoji('search')} Подбор email…"
    )
    ph = (phase or "").strip().lower()
    if not finished and ph == "saving":
        title = f"{html_emoji('wait')} Сохраняю в БД…"
    elif not finished and ph == "api_retry":
        title = f"{html_emoji('wait')} Повтор после сбоев API…"
    elif not finished and ph == "export":
        title = f"{html_emoji('wait')} Отправляю файл…"

    bar_total = total
    bar_done = processed
    rq = rd = 0
    if not finished and ph == "api_retry":
        rq = int(api_retry_queued or 0)
        rd = int(api_retry_done or 0)
        if rq > 0:
            bar_total = rq
            bar_done = min(rd, rq)
        else:
            bar_done = min(seller_index, max(0, sellers_total - 1))
            bar_total = max(sellers_total, 1)
    elif not finished and sellers_total > 0 and ph not in ("saving", "export"):
        bar_total = sellers_total
        bar_done = min(seller_index, max(0, sellers_total - 1))

    bar, pct = _progress_bar(bar_done, bar_total)
    if not finished and ph == "saving":
        pct = 98
        bar, _ = _progress_bar(98, 100)
    elif not finished and ph == "export":
        pct = 99
        bar, _ = _progress_bar(99, 100)
    elif not finished and ph == "api_retry" and rq > 0 and rd < rq:
        pct = min(pct, 98)
    elif (
        not finished
        and sellers_total > 0
        and seller_index >= sellers_total
        and ph not in ("saving", "export", "api_retry")
    ):
        pct = min(pct, 97)

    lines = [
        f"<b>{title}</b>",
        user_line,
        f"<code>{bar}</code> <b>{pct}%</b>",
    ]
    bl_total = int(added_blacklist or 0) + int(in_blacklist or 0)
    nick_total = int(short_nicks or 0) + int(no_name or 0)
    already_n = int(already_in_db or 0)
    not_found = int(no_email_smtp if finished else no_email)
    if not finished and ph == "api_retry":
        not_found = 0
    unresolved = int(sellers_api_unresolved or 0)
    # В финале всё без найденной почты = «Без email» (в т.ч. SMTP unknown).
    no_email_total = not_found + unresolved if finished else not_found
    if finished and int(listings_in_file or 0) > 0:
        lines.append("")
        lines.append(
            f"{html_emoji('presets')} В JSON: <b>{int(listings_in_file)}</b> объявлений · "
            f"в API: <b>{int(offers_eligible or 0)}</b> продавцов "
            f"(1 имя = 1 проверка)"
        )
    lines.extend(
        [
            "",
            f"{html_emoji('email')} Новых email: <b>{added}</b>",
            f"{html_emoji('ok')} Уже в БД (не гоняем API): <b>{already_n}</b>",
            f"{html_emoji('fail')} ЧС: <b>{bl_total}</b> · повтор имени в файле: <b>{int(duplicates or 0)}</b> · ник/нет имени: <b>{nick_total}</b>",
            f"{html_emoji('wait')} Без email: <b>{no_email_total}</b>",
        ]
    )
    # В процессе можно показать, что часть ещё «висит» на SMTP; в финале — только «Без email».
    if not finished and int(sellers_api_unresolved or 0) > 0:
        lines.append(
            f"{html_emoji('wait')} Ждём SMTP: <b>{int(sellers_api_unresolved)}</b>"
        )
    return "\n".join(lines)


def _norm_email(e: str) -> str:
    """Нормализация email для сохранения/поиска.

    - lower + strip
    - googlemail.com -> gmail.com
    - для gmail: убираем +tag (first.last+tag@gmail.com)
    """
    s = (e or "").strip().lower()
    if not s or "@" not in s:
        return ""
    local, domain = s.split("@", 1)
    domain = domain.strip()
    if domain == "googlemail.com":
        domain = "gmail.com"
    if domain == "gmail.com" and "+" in local:
        local = local.split("+", 1)[0]
    local = local.strip()
    if not local:
        return ""
    return f"{local}@{domain}"


def _collect_raw_emails(raw: dict) -> list[str]:
    """Достаём "реальные" email из сырого item (если они там есть).

    Это НЕ меняет логику валидации. Только помогает потом найти Offer.link
    по фактическому from_email входящего письма.
    """
    out: list[str] = []
    if not isinstance(raw, dict):
        return out

    # самые явные поля
    for key in ("email", "seller_email", "contact_email", "from_email", "owner_email", "account_email"):
        v = raw.get(key)
        if isinstance(v, str) and "@" in v:
            out.append(v)

    # иногда прилетает списком
    v2 = raw.get("emails")
    if isinstance(v2, list):
        for x in v2:
            if isinstance(x, str) and "@" in x:
                out.append(x)

    v3 = raw.get("validated_emails")
    if isinstance(v3, list):
        for x in v3:
            if isinstance(x, str) and "@" in x:
                out.append(x)

    return out


# ===================== LOADERS =====================


async def _load_json_from_telegram_doc(message: Message) -> Any:
    file = await message.bot.download(message.document)
    raw = file.read()
    for enc in ("utf-8-sig", "utf-8", "cp1251", "latin-1"):
        try:
            text = raw.decode(enc)
            return json.loads(text)
        except Exception:
            continue
    # последняя попытка — как есть
    return json.loads(raw.decode("utf-8", errors="replace"))


async def _load_text_from_telegram_doc(message: Message) -> str:
    file = await message.bot.download(message.document)
    raw = file.read()
    for enc in ("utf-8-sig", "utf-8", "cp1251", "latin-1"):
        try:
            return raw.decode(enc)
        except Exception:
            continue
    return raw.decode("utf-8", errors="replace")


# ===================== PARSERS =====================

_WORD_RE = re.compile(r"[A-Za-zÀ-ÿ0-9]+")


def _normalize_person_name(raw_name: str) -> str:
    """Нормализовать имя продавца; ники с _ или без пробелов — как в JSON."""
    from services.seller_name import (
        is_name_honorific_token,
        normalize_seller_name,
        strip_name_honorifics,
    )

    s = (raw_name or "").strip()
    if not s:
        return ""
    compact = re.sub(r"\s+", "", s)
    if " " not in s and re.fullmatch(r"[A-Za-z0-9_\-]+", compact):
        return s.strip()
    # Dr. Michael Raufeisen → Michael Raufeisen (не Dr + фамилия)
    cleaned = strip_name_honorifics(s)
    folded = normalize_seller_name(cleaned)
    words = _WORD_RE.findall(folded)
    words = [w for w in words if not is_name_honorific_token(w)]
    if not words:
        return cleaned or s
    if len(words) == 1:
        return words[0]
    return f"{words[0]} {words[-1]}"


def _normalize_items(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Нормализация структуры items из JSON.

    Здесь мы аккуратно синхронизируем ключевые поля:
    - person_name/name/item_person_name -> нормализованный person_name
    - title/item_title
    - price/item_price
    - link/item_link
    Ничего "умного" не изобретаем, просто приводим к единому виду.
    """
    out: List[Dict[str, Any]] = []
    for x in items or []:
        from services.offer_storage import _title_from_item_dict, fields_from_item

        y = dict(x)
        fields = fields_from_item(y)
        raw_name = seller_name_from_item(y)

        norm = _normalize_person_name(raw_name)
        if norm:
            y["name"] = norm
            y["person_name"] = norm
            # Оригинал из JSON не теряем (Irene / Bregenznet / seller_name).
            if not str(y.get("item_person_name") or "").strip():
                y["item_person_name"] = raw_name or norm
            if not str(y.get("seller_name") or "").strip():
                y["seller_name"] = raw_name or norm

        t = fields["title"] or _title_from_item_dict(x)
        if t:
            y["item_title"] = t
            y["title"] = t
        elif "title" not in y and isinstance(x.get("item_title"), str):
            y["title"] = x["item_title"]
        link = fields["link"]
        if link:
            y["item_link"] = link
            y["link"] = link
        elif "link" not in y and isinstance(x.get("item_link"), str):
            y["link"] = x["item_link"]
        price = fields["price"]
        currency = str(x.get("currency") or "").strip()
        if price:
            if currency and currency.upper() not in price.upper():
                price = f"{price} {currency}"
            y["item_price"] = price
            y["price"] = price
        elif "price" not in y and isinstance(x.get("item_price"), (str, int, float)):
            y["price"] = str(x["item_price"])
        photo = fields["photo"]
        if photo:
            y["item_photo"] = photo
            y["photo"] = photo

        out.append(y)
    return out


def _extract_items(data: Any) -> List[Dict[str, Any]]:
    """Вытащить список офферов из произвольного JSON (VOID / xproject void_parser)."""
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        for key in ("items", "offers", "ads", "results", "data", "listings"):
            val = data.get(key)
            if isinstance(val, list):
                return [x for x in val if isinstance(x, dict)]
            if isinstance(val, dict):
                nested = val.get("items") or val.get("offers") or val.get("ads")
                if isinstance(nested, list):
                    return [x for x in nested if isinstance(x, dict)]
        # одиночный лот
        if any(
            k in data
            for k in ("item_link", "item_title", "link", "title", "url", "seller_name")
        ):
            return [data]
    return []


def _parse_txt_offers(text: str) -> List[Dict[str, Any]]:
    """Парсер txt-файла в список словарей (fallback-формат)."""
    t = (text or "").replace("\r\n", "\n").replace("\r", "\n")

    # блоки отделяем пустыми строками
    blocks = [b.strip() for b in t.split("\n\n") if b.strip()]

    items: List[Dict[str, Any]] = []
    for block in blocks:
        title = ""
        seller = ""

        for line in block.split("\n"):
            s = line.strip()
            if not s:
                continue
            if "Продавец" in s or s.startswith("💼"):
                seller = s.split(":", 1)[-1].strip()
            elif not title and not s.startswith("🔗"):
                title = s.lstrip("📱").strip()

        m = re.search(r"(https?://[^\s\)]+)", block)
        link = m.group(1).strip() if m else ""

        if title or link:
            items.append(
                {
                    "title": title,
                    "item_title": title,
                    "person_name": seller,
                    "item_person_name": seller,
                    "link": link,
                    "item_link": link,
                }
            )

    return items


# ===================== MAIN HANDLER =====================


@router.message(Command("stopvalid", "stopvalidation", "cancelvalid"))
async def stop_validation_handler(message: Message):
    tg_id = message.from_user.id
    if not bg_is_running(tg_id, "validation"):
        return await message.answer(
            f"{html_emoji('ok')} Подбор email сейчас не выполняется.",
            parse_mode="HTML",
        )
    bg_cancel(tg_id, "validation")
    _validation_snapshots.pop(int(tg_id), None)
    await message.answer(
        f"{html_emoji('warn')} Останавливаю подбор… Через несколько секунд можно прислать JSON снова.",
        parse_mode="HTML",
    )


@router.message(F.document)
async def validation_handler(message: Message):
    ext = (message.document.file_name or "").lower()
    if not ext.endswith((".json", ".txt")):
        return await message.answer(f"{html_emoji('fail')} Пришли файл .json или .txt", parse_mode="HTML")

    try:
        status_msg = await message.answer(
            f"{html_emoji('wait')} Файл получен, читаю…",
            parse_mode="HTML",
        )
    except Exception:
        status_msg = None

    try:
        if ext.endswith(".json"):
            data = await _load_json_from_telegram_doc(message)
            items = _normalize_items(_extract_items(data))
        else:
            text = await _load_text_from_telegram_doc(message)
            items = _parse_txt_offers(text)
    except Exception as e:
        err = f"{html_emoji('fail')} Ошибка чтения файла: {e}"
        if status_msg:
            return await status_msg.edit_text(err, parse_mode="HTML")
        return await message.answer(err, parse_mode="HTML")

    if not items:
        err = f"{html_emoji('fail')} В файле не найдено записей."
        if status_msg:
            return await status_msg.edit_text(err, parse_mode="HTML")
        return await message.answer(err, parse_mode="HTML")

    tg_id = message.from_user.id
    if bg_is_running(tg_id, "validation"):
        bg_cancel(tg_id, "validation")
        _validation_snapshots.pop(int(tg_id), None)
        await asyncio.sleep(0.4)

    if status_msg:
        try:
            await status_msg.edit_text(
                f"{html_emoji('search')} <b>Подбор email…</b>\n"
                f"{_validation_user_line(message)}\n"
                f"В JSON: <b>{len(items)}</b> объявлений — запускаю API.",
                parse_mode="HTML",
            )
        except Exception:
            pass

    async def _validation_job() -> None:
        await _run_validation_pipeline(message, status_msg, items)

    if not bg_start(tg_id, "validation", _validation_job()):
        hint = _running_validation_hint(tg_id)
        if status_msg:
            try:
                await status_msg.edit_text(hint, parse_mode="HTML")
            except Exception:
                pass
            return
        return await message.answer(hint, parse_mode="HTML")


async def _run_validation_pipeline(message: Message, status_msg: Message, items: list) -> None:
    total_offers = len(items)
    user_line = _validation_user_line(message)
    tg_id = message.from_user.id
    _validation_snapshots[int(tg_id)] = {"offers_total": total_offers, "seller_index": 0}

    try:
        await _run_validation_pipeline_inner(
            message, status_msg, items, total_offers, user_line, tg_id
        )
    except asyncio.CancelledError:
        try:
            if status_msg:
                await status_msg.edit_text(
                    f"{html_emoji('warn')} Подбор остановлен (<code>/stopvalid</code>).",
                    parse_mode="HTML",
                )
        except Exception:
            pass
        raise
    except Exception as e:
        logger.exception("validation pipeline failed tg=%s", tg_id)
        try:
            if status_msg:
                await status_msg.edit_text(
                    f"{html_emoji('fail')} Ошибка подбора: {e}",
                    parse_mode="HTML",
                )
        except Exception:
            pass
    finally:
        _validation_snapshots.pop(int(tg_id), None)


async def _run_validation_pipeline_inner(
    message: Message,
    status_msg: Message,
    items: list,
    total_offers: int,
    user_line: str,
    tg_id: int,
) -> None:
    try:
        await status_msg.edit_text(
            f"{html_emoji('search')} <b>Подбор email…</b>\n"
            f"{user_line}\n"
            f"В JSON: <b>{total_offers}</b> объявлений — запускаю API.",
            parse_mode="HTML",
        )
    except Exception:
        pass

    async with db_session() as session:
        user = await get_or_create_user(session, tg_id)

        api_keys = resolve_validemail_api_keys()

        if not api_keys:
            return await status_msg.edit_text(
                f"{html_emoji('fail')} Ключи валидации не заданы.\n\n"
                "Лёгкие домены (gmail/icloud): <code>VALIDEMAIL_API_KEYS=mailcheck</code>\n"
                "Сложные (GMX/web/bluewin): <code>VALIDEMAIL_HARD_URL=https://validemail.co/api/v1/validate</code>\n"
                "и <code>VALIDEMAIL_HARD_API_KEYS=key1,key2,…</code>",
                parse_mode="HTML",
            )

        # ✅ Приоритет доменов: берём порядок из "Настройки -> Приоритет отправки" (user_setting: domain_priority).
        # Если приоритет не задан — используем порядок как в БД (Domain.id).
        db_domains = [
            (d.domain or "").strip().lower()
            for d in (
                await session.execute(
                    select(Domain).where(Domain.user_id == user.id).order_by(Domain.id)
                )
            ).scalars().all()
            if (d.domain or "").strip()
        ]

        from services.country_scope import default_validation_domains_for, get_scoped_setting
        from services.enabled_countries import get_active_country

        cc = await get_active_country(session, user)
        priority_raw = await get_scoped_setting(session, user, "domain_priority", country=cc)
        # domain_priority is normally stored as JSON list (see settings.py),
        # but older DBs / migrations may contain raw text with newlines.
        priority_list = []
        if priority_raw:
            try:
                priority_list = json.loads(priority_raw)
            except Exception:
                priority_list = [x.strip() for x in str(priority_raw).splitlines() if x.strip()]
        if not isinstance(priority_list, list):
            priority_list = []

        pr = [str(x or "").strip().lower() for x in priority_list if str(x or "").strip()]
        if cc == "nl":
            domains = merge_validation_domains(pr + db_domains)
            if not domains:
                domains = merge_validation_domains(list(default_validation_domains_for(cc)))
        else:
            domains = merge_validation_domains(pr or list(default_validation_domains_for(cc)))

        if not domains:
            return await status_msg.edit_text(
                f"{html_emoji('fail')} У тебя нет доменов.",
                parse_mode="HTML",
            )

    async with db_session() as session:
        user_bl = await get_or_create_user(session, tg_id)
        from services.seller_blacklist import (
            load_seller_keys_with_validated_email,
            load_seller_name_keys,
        )

        append_active = await is_user_mailing_active(tg_id)
        already_keys = await load_seller_keys_with_validated_email(session, int(user_bl.id))
        chs_keys = await load_seller_name_keys(
            session,
            int(user_bl.id),
            include_offer_names=False,
        )
        # Имена в ЧС всегда стопают API (не только пока OfferEmail жив).
        if append_active:
            with_offers = await load_seller_name_keys(
                session,
                int(user_bl.id),
                include_offer_names=True,
            )
            already_keys |= with_offers - chs_keys

    from services.validemail_keys import hard_backend_enabled, resolve_hard_api_keys, validation_traffic_mode

    n_keys = len(api_keys)
    hard_keys = resolve_hard_api_keys() if hard_backend_enabled() else []
    from services.validemail_keys import hard_validation_url

    pool_easy = validation_pool_size(n_keys)
    pool_hard = 0
    if hard_keys:
        pool_hard = per_key_concurrency_limit(hard_validation_url()) * len(hard_keys)
    pool = max(2, pool_easy, pool_hard)
    per_key_lim = per_key_concurrency_limit()
    cfg = ValidationConfig(
        validemail_api_keys=api_keys,
        validation_url=config.VALIDEMAIL_URL,
        concurrency=max(2, pool),
        max_emails_per_seller=MAX_EMAILS_PER_SELLER,
        require_first_and_last=REQUIRE_FIRST_AND_LAST,
        max_len=40,
        min_len=seller_name_min_letters(cc),
        country=cc,
        seller_name_keys=chs_keys,
        already_validated_names=already_keys,
    )

    live_stats: dict = {
        "offers_total": total_offers,
        "validemail_keys": n_keys,
        "validemail_hard_keys": len(hard_keys),
        "validemail_pool": pool,
        "validemail_per_key": per_key_lim,
        "validemail_threads": n_keys,
        "traffic_mode": validation_traffic_mode(),
        "validation_t0": time.time(),
    }
    ui_state = {"last_text": ""}
    stop_evt = asyncio.Event()

    def _progress_cb(done: int, total: int, limit: int, in_use: int) -> None:
        pass

    def _ui_from_stats(vstats: dict, *, finished: bool = False) -> str:
        total = int(vstats.get("offers_total") or total_offers)
        seller_i = int(vstats.get("seller_index") or 0)
        added = int(vstats.get("sellers_with_email") or 0)
        short_n = int(vstats.get("short_nicks") or 0)
        bl = int(vstats.get("blacklisted") or 0)
        already_db = int(vstats.get("already_in_db") or 0)
        no_name = int(vstats.get("no_name") or 0)
        dup = int(vstats.get("duplicates") or 0)
        err = int(vstats.get("api_errors") or 0)
        skip_fixed = short_n + bl + no_name + already_db + dup
        if finished:
            processed = total
        else:
            processed = min(total, skip_fixed + seller_i)
        eligible = int(vstats.get("offers_eligible") or 0)
        if finished:
            api_u = int(vstats.get("sellers_api_unresolved") or 0)
            no_email = max(0, eligible - added - api_u)
            no_email_smtp = no_email
        else:
            api_u = int(vstats.get("sellers_api_unresolved") or 0)
            no_email_smtp = max(0, seller_i - added - api_u)
            no_email = no_email_smtp
        return _format_validation_status(
            finished=finished,
            user_line=user_line,
            processed=processed,
            total=total,
            added=added,
            duplicates=dup,
            in_blacklist=0,
            added_blacklist=bl,
            short_nicks=short_n,
            no_email=no_email,
            errors=err,
            sellers_api_unresolved=int(vstats.get("sellers_api_unresolved") or 0),
            no_email_smtp=no_email_smtp,
            validemail_keys=int(vstats.get("validemail_keys") or 0),
            validemail_pool=int(vstats.get("validemail_pool") or 0),
            validemail_per_key=int(vstats.get("validemail_per_key") or 0),
            validemail_threads=int(vstats.get("validemail_threads") or 0),
            phase=str(vstats.get("phase") or ""),
            sellers_total=int(vstats.get("sellers_total") or 0),
            seller_index=seller_i,
            validemail_domains=int(vstats.get("domains_count") or 0),
            validemail_max_locals=int(vstats.get("max_locals") or 0),
            validemail_api_timeout=int(vstats.get("validemail_api_timeout") or 0),
            traffic_mode=bool(vstats.get("traffic_mode")),
            priority_domains=vstats.get("priority_domains") if isinstance(vstats.get("priority_domains"), list) else None,
            current_domain=str(vstats.get("current_domain") or ""),
            validation_t0=float(vstats.get("validation_t0") or 0),
            seller_parallel_cap=int(vstats.get("seller_parallel_cap") or 0),
            api_retry_queued=int(vstats.get("api_retry_queued") or 0),
            api_retry_done=int(vstats.get("api_retry_done") or 0),
            seller_timeouts=int(vstats.get("seller_timeouts") or 0),
            offers_eligible=int(vstats.get("offers_eligible") or 0),
            listings_in_file=int(vstats.get("offers_total") or total_offers),
            no_name=int(vstats.get("no_name") or 0),
            already_in_db=already_db,
        )

    try:
        await status_msg.edit_text(
            _ui_from_stats(live_stats, finished=False), parse_mode="HTML"
        )
    except Exception:
        pass

    async def _progress_updater(msg: Message, stop: asyncio.Event, vstats: dict) -> None:
        while not stop.is_set():
            _validation_snapshots[int(tg_id)] = dict(vstats)
            text = _ui_from_stats(vstats, finished=False)
            if text != ui_state.get("last_text"):
                try:
                    await msg.edit_text(text, parse_mode="HTML")
                    ui_state["last_text"] = text
                except Exception:
                    pass
            await asyncio.sleep(PROGRESS_UPDATE_INTERVAL)

    updater = asyncio.create_task(_progress_updater(status_msg, stop_evt, live_stats))

    try:
        validated = await validate_offers(
            items, domains, cfg, progress_cb=_progress_cb, stats=live_stats
        )
    finally:
        stop_evt.set()
        await updater

    live_stats["phase"] = "saving"
    try:
        await status_msg.edit_text(
            _ui_from_stats(live_stats, finished=False), parse_mode="HTML"
        )
    except Exception:
        pass

    validated_count = len(validated or [])
    eligible = int(live_stats.get("offers_eligible") or 0)

    append_to_active_mailing = False
    total_in_db = 0

    async with db_session() as session:
        user = await get_or_create_user(session, tg_id)

        append_to_active_mailing = await is_user_mailing_active(tg_id)
        # Не сносим offers: тот же item_link = тот же id; новый JSON только добавляет/обновляет.

        from services.mailing_reset import get_mailing_reset_skip_emails

        skip_emails = await get_mailing_reset_skip_emails(session, int(user.id))
        offers_saved, offers_with_email, saved_email_count, output = await save_all_offers_from_import(
            session,
            user_id=int(user.id),
            items=items,
            validated_rows=validated or [],
            norm_email=_norm_email,
            max_emails_per_offer=MAX_EMAILS_PER_OFFER,
            skip_queue_emails=skip_emails or None,
        )
        await session.commit()

        from sqlalchemy import func as sql_func

        total_in_db = (
            await session.execute(
                select(sql_func.count(Offer.id)).where(Offer.user_id == user.id)
            )
        ).scalar() or 0

        from services.seller_blacklist import (
            add_seller_name_blacklist_bulk,
            seller_keys_from_saved_output,
        )

        saved_name_keys = seller_keys_from_saved_output(output)
        if saved_name_keys:
            await add_seller_name_blacklist_bulk(session, int(user.id), saved_name_keys)
            await session.commit()

        if append_to_active_mailing and saved_email_count > 0:
            pending_now = (
                await session.execute(
                    select(sql_func.count(OfferEmail.id))
                    .select_from(OfferEmail)
                    .join(Offer, OfferEmail.offer_id == Offer.id)
                    .where(Offer.user_id == user.id)
                )
            ).scalar() or 0
            st = get_sending_state(tg_id)
            if st and st.is_running:
                st.total_targets = int(st.sent_count) + int(st.failed_count) + int(pending_now)
                set_sending_state(tg_id, st)

    out_path = os.path.join(
        tempfile.gettempdir(),
        f"validated_{tg_id}_{int(time.time())}.json"
    )

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(
            format_validated_export_document(output),
            f,
            ensure_ascii=False,
            indent=2,
        )

    live_stats["sellers_with_email"] = offers_with_email
    live_stats["offers_eligible"] = eligible

    append_note = (
        f" · {html_emoji('add')} добавлено к активной рассылке"
        if append_to_active_mailing
        else ""
    )
    skip_note = (
        f" · в БД всего лотов: <b>{int(total_in_db)}</b> (накопительно, не сбрасывается)"
    )

    live_stats["phase"] = "export"
    try:
        await status_msg.edit_text(
            _ui_from_stats(live_stats, finished=False), parse_mode="HTML"
        )
    except Exception:
        pass

    async def _deliver_validated_json() -> None:
        try:
            await asyncio.wait_for(
                message.answer_document(
                    FSInputFile(out_path),
                    caption=(
                        f"{html_emoji('presets')} Результат · новых {offers_saved} · "
                        f"в файле {len(output)}/{total_offers} · "
                        f"email {saved_email_count}{append_note}{skip_note}"
                    ),
                    parse_mode="HTML",
                ),
                timeout=180.0,
            )
        except asyncio.TimeoutError:
            logger.warning("validation: document upload timeout tg=%s", tg_id)
            try:
                await message.answer(
                    f"{html_emoji('warn')} JSON не успел уйти за 3 мин — данные уже в БД. "
                    f"Повтори /export или пришли файл ещё раз.",
                    parse_mode="HTML",
                )
            except Exception:
                pass
        except Exception:
            logger.exception("validation: document upload failed tg=%s", tg_id)
        finally:
            try:
                os.remove(out_path)
            except OSError:
                pass

    try:
        await _deliver_validated_json()
    finally:
        live_stats["phase"] = ""

    try:
        await status_msg.edit_text(
            _ui_from_stats(live_stats, finished=True), parse_mode="HTML"
        )
    except Exception:
        pass
