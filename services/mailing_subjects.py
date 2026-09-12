"""Персональный список тем писем: random / fixed + OFFER."""

from __future__ import annotations

import json
import random
from typing import Any, Literal, Sequence

from services.country_scope import get_scoped_setting, set_scoped_setting

MAIL_SUBJECT_LIST_KEY = "mail_subject_list"
MAIL_SUBJECT_MODE_KEY = "mail_subject_mode"
MAIL_SUBJECT_FIXED_KEY = "mail_subject_fixed"

SubjectMode = Literal["random", "fixed"]
PAGE_SIZE = 5
MAX_LINES = 300
MAX_LINE_LEN = 140


def parse_subject_lines(raw: str) -> list[str]:
    """Многострочный ввод → список тем (пустые строки пропускаются)."""
    out: list[str] = []
    seen: set[str] = set()
    for line in (raw or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        s = " ".join((line or "").split()).strip()
        if not s:
            continue
        if len(s) > MAX_LINE_LEN:
            s = s[: MAX_LINE_LEN - 1] + "…"
        key = s.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
        if len(out) >= MAX_LINES:
            break
    return out


def _loads_list(raw: str | None) -> list[str]:
    if not (raw or "").strip():
        return []
    text = raw.strip()
    if text.startswith("["):
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            data = None
        if isinstance(data, list):
            out: list[str] = []
            for item in data:
                s = " ".join(str(item or "").split()).strip()
                if s:
                    out.append(s[:MAX_LINE_LEN])
            return out[:MAX_LINES]
    return parse_subject_lines(text)


async def get_subject_lines(session, user) -> list[str]:
    raw = await get_scoped_setting(session, user, MAIL_SUBJECT_LIST_KEY)
    return _loads_list(raw)


async def set_subject_lines(session, user, lines: Sequence[str]) -> list[str]:
    clean = parse_subject_lines("\n".join(str(x) for x in lines))
    await set_scoped_setting(session, user, MAIL_SUBJECT_LIST_KEY, json.dumps(clean, ensure_ascii=False))
    if not clean:
        await set_scoped_setting(session, user, MAIL_SUBJECT_FIXED_KEY, "0")
        return clean
    idx = await get_fixed_index(session, user)
    if idx < 0 or idx >= len(clean):
        await set_fixed_index(session, user, 0)
    return clean


async def get_subject_mode(session, user) -> SubjectMode:
    raw = ((await get_scoped_setting(session, user, MAIL_SUBJECT_MODE_KEY)) or "").strip().lower()
    if raw in ("fixed", "fix", "only_fixed", "только"):
        return "fixed"
    return "random"


async def set_subject_mode(session, user, mode: SubjectMode) -> None:
    await set_scoped_setting(session, user, MAIL_SUBJECT_MODE_KEY, "fixed" if mode == "fixed" else "random")


async def get_fixed_index(session, user) -> int:
    raw = ((await get_scoped_setting(session, user, MAIL_SUBJECT_FIXED_KEY)) or "0").strip()
    try:
        return max(0, int(raw))
    except ValueError:
        return 0


async def set_fixed_index(session, user, index: int) -> None:
    await set_scoped_setting(session, user, MAIL_SUBJECT_FIXED_KEY, str(max(0, int(index))))


def pick_template_from_list(
    lines: Sequence[str],
    *,
    mode: SubjectMode,
    fixed_index: int = 0,
) -> str | None:
    if not lines:
        return None
    if mode == "fixed":
        i = fixed_index if 0 <= fixed_index < len(lines) else 0
        return lines[i]
    return random.choice(list(lines))


async def resolve_user_subject_template(session, user) -> str | None:
    """Шаблон темы пользователя или None → fallback на глобальную ротацию."""
    lines = await get_subject_lines(session, user)
    if not lines:
        return None
    mode = await get_subject_mode(session, user)
    idx = await get_fixed_index(session, user)
    return pick_template_from_list(lines, mode=mode, fixed_index=idx)


async def mailing_subject_for_user(session, user, offer_title: str) -> str:
    from services.subject_offer import pick_mailing_subject, render_subject_with_offer

    tpl = await resolve_user_subject_template(session, user)
    if tpl:
        return render_subject_with_offer(tpl, offer_title or "")
    return pick_mailing_subject(offer_title or "")


def mode_label(mode: SubjectMode) -> str:
    if mode == "fixed":
        return "только фиксированная"
    return "случайная из списка"


def page_count(total: int, page_size: int = PAGE_SIZE) -> int:
    if total <= 0:
        return 1
    return (total + page_size - 1) // page_size


def clamp_page(page: int, total: int, page_size: int = PAGE_SIZE) -> int:
    pages = page_count(total, page_size)
    return min(max(0, int(page)), pages - 1)
