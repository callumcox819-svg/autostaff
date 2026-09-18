"""Импорт умных пресетов из .txt (одна строка = один пресет)."""

from __future__ import annotations

import re

MAX_TXT_IMPORT_LINES = 500
MAX_SMART_PRESETS_TOTAL = 600
MIN_PRESET_LEN = 2

_ITEM_TITLE_RE = re.compile(
    r"\[\[\s*ITEM_TITLE\s*\]\]"
    r"|\{\{\s*ITEM_TITLE\s*\}\}"
    r"|\[\s*ITEM_TITLE\s*\]",
    re.I,
)


def normalize_smart_preset_line(line: str) -> str:
    s = (line or "").replace("\ufeff", "").strip()
    if not s:
        return ""
    s = _ITEM_TITLE_RE.sub("OFFER", s)
    s = s.replace("{{OFFER}}", "OFFER")
    return s.strip()


def parse_smart_presets_txt(raw: str) -> list[str]:
    """Непустые строки файла → тексты пресетов с OFFER вместо ITEM_TITLE."""
    out: list[str] = []
    for line in (raw or "").splitlines():
        if len(out) >= MAX_TXT_IMPORT_LINES:
            break
        norm = normalize_smart_preset_line(line)
        if len(norm) < MIN_PRESET_LEN:
            continue
        out.append(norm[:4000])
    return out


def merge_smart_presets(existing: list[str], imported: list[str]) -> tuple[list[str], int, int]:
    """Добавляет imported в конец. Returns (merged, added_count, skipped_over_cap)."""
    base = list(existing or [])
    added = 0
    skipped = 0
    for row in imported:
        if len(base) >= MAX_SMART_PRESETS_TOTAL:
            skipped += 1
            continue
        base.append(row)
        added += 1
    return base, added, skipped


def replace_smart_presets(imported: list[str]) -> tuple[list[str], int]:
    """Новый TXT — полный набор пресетов; старые строки не подмешиваются."""
    rows = list(imported or [])
    selected = rows[:MAX_SMART_PRESETS_TOTAL]
    return selected, max(0, len(rows) - len(selected))
