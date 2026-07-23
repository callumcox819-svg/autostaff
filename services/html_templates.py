"""HTML-шаблоны по сервису GAG (ricardo_ch / tutti_ch)."""

from __future__ import annotations

from pathlib import Path

from region import HTML_DATA_DIR
from services.aqua_keys import (
    aqua_service_for_html_dir,
    is_valid_aqua_service,
    normalize_aqua_service,
)

HTML_ROOT = Path("data") / HTML_DATA_DIR

GO_FILENAME = "confirmation.html"
GO_NEW_FILENAME = "confirmation_new.html"
BACK_FILENAME = "return.html"


def html_subdir_for_service(service_code: str | None) -> str | None:
    if not is_valid_aqua_service(service_code):
        return None
    sub = aqua_service_for_html_dir(service_code)
    return sub or None


def html_template_path(service_code: str | None, filename: str) -> Path | None:
    sub = html_subdir_for_service(service_code)
    if not sub:
        return None
    p = HTML_ROOT / sub / filename
    return p if p.is_file() else None


def list_html_templates_for_service(service_code: str | None) -> list[str]:
    sub = html_subdir_for_service(service_code)
    if not sub:
        return []
    d = HTML_ROOT / sub
    if not d.is_dir():
        return []
    return sorted(f.name for f in d.glob("*.html"))


def service_label_for_path(subdir: str) -> str:
    if subdir == "ricardo_ch":
        return "ricardo.ch"
    if subdir == "tutti_ch":
        return "tutti.ch"
    return subdir


def canonical_service_name(service_code: str | None) -> str | None:
    return normalize_aqua_service(service_code)


async def load_html_for_user(
    session,
    user,
    *,
    aqua_service_key: str,
    filename: str,
) -> tuple[str, str | None, str | None]:
    from services.aqua_keys import AQUA_SERVICE_KEY, get_user_aqua_service
    from services.user_settings import get_user_setting

    raw = (await get_user_aqua_service(session, user)).strip()
    if not raw:
        raw = (await get_user_setting(session, user, aqua_service_key or AQUA_SERVICE_KEY) or "").strip()
    if not is_valid_aqua_service(raw):
        return (
            "",
            None,
            "Не выбран сервис. Открой 👤 Профиль → 🧭 Сервис (ricardo / tutti).",
        )
    sub = html_subdir_for_service(raw)
    p = html_template_path(raw, filename)
    if not p:
        label = service_label_for_path(sub or "")
        return "", sub, f"Шаблон <code>{filename}</code> не найден для сервиса <b>{label}</b>."
    try:
        return p.read_text(encoding="utf-8"), sub, None
    except OSError as e:
        return "", sub, f"Не удалось прочитать шаблон: {e}"
