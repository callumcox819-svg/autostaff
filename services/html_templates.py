"""HTML-шаблоны ответов: data/HTML/<service>/…"""

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
BACK_FILENAME = "back.html"
# BACK: back.html, иначе старое имя return.html
_FILE_ALIASES: dict[str, tuple[str, ...]] = {
    "back.html": ("back.html", "return.html"),
    "return.html": ("return.html", "back.html"),
}


def html_subdir_for_service(service_code: str | None) -> str | None:
    code = (service_code or "").strip().lower()
    if not code:
        return None
    if (HTML_ROOT / code / "confirmation.html").is_file():
        return code
    if not is_valid_aqua_service(code):
        return None
    sub = aqua_service_for_html_dir(code)
    return sub or None


def html_template_path(service_code: str | None, filename: str) -> Path | None:
    sub = html_subdir_for_service(service_code)
    if not sub:
        return None
    names = _FILE_ALIASES.get(filename, (filename,))
    for name in names:
        p = HTML_ROOT / sub / name
        if p.is_file():
            return p
    return None


def list_html_templates_for_service(service_code: str | None) -> list[str]:
    sub = html_subdir_for_service(service_code)
    if not sub:
        return []
    d = HTML_ROOT / sub
    if not d.is_dir():
        return []
    return sorted(f.name for f in d.glob("*.html"))


def service_label_for_path(subdir: str) -> str:
    return (subdir or "").strip() or "—"


def canonical_service_name(service_code: str | None) -> str | None:
    return normalize_aqua_service(service_code)


async def load_html_for_user(
    session,
    user,
    *,
    aqua_service_key: str,
    filename: str,
) -> tuple[str, str | None, str | None]:
    from services.aqua_keys import resolve_html_service

    raw = (await resolve_html_service(session, user) or "").strip()
    p = html_template_path(raw, filename)
    if not p:
        sub = html_subdir_for_service(raw)
        label = service_label_for_path(sub or raw or "—")
        return (
            "",
            sub,
            f"Шаблон <code>{filename}</code> не найден для <b>{label}</b> "
            f"(положи файл в <code>data/{HTML_DATA_DIR}/{label}/</code>).",
        )
    try:
        return p.read_text(encoding="utf-8"), html_subdir_for_service(raw), None
    except OSError as e:
        return "", html_subdir_for_service(raw), f"Не удалось прочитать шаблон: {e}"
