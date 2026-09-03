"""re.sub с буквальной подстановкой (без \\1 / octal в replacement)."""

from __future__ import annotations

import re
from typing import Pattern


def re_sub_literal(
    pattern: str | Pattern[str],
    repl: str,
    string: str,
    *,
    count: int = 0,
    flags: int = 0,
) -> str:
    """Как re.sub, но repl всегда как обычный текст (названия лотов, ссылки, адреса)."""
    lit = "" if repl is None else str(repl)

    def _keep(_m: re.Match[str]) -> str:
        return lit

    if isinstance(pattern, str):
        return re.sub(pattern, _keep, string or "", count=count, flags=flags)
    if count:
        return pattern.sub(_keep, string or "", count=count)
    return pattern.sub(_keep, string or "")
