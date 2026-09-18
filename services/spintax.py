from __future__ import annotations

import random
import re


_PLACEHOLDER_RE = re.compile(r"\{\{\s*[A-Z0-9_]+\s*\}\}", re.I)


def expand_spintax(text: str, *, max_passes: int = 30) -> str:
    """Expand simple spintax like: {Hi|Hello}.

    Supports nesting: {Hi|{Hello|Hey}}.
    """
    if not text:
        return ""

    s = str(text)
    placeholders: list[str] = []

    def _protect_placeholder(match: re.Match[str]) -> str:
        index = len(placeholders)
        placeholders.append(match.group(0))
        return f"\x00PLACEHOLDER_{index}\x00"

    s = _PLACEHOLDER_RE.sub(_protect_placeholder, s)
    for _ in range(max_passes):
        start = s.rfind("{")
        if start == -1:
            break
        end = s.find("}", start)
        if end == -1:
            break
        inner = s[start + 1 : end]
        # allow empty options, filter only completely empty?
        options = inner.split("|")
        choice = random.choice(options) if options else ""
        s = s[:start] + choice + s[end + 1 :]

    for index, placeholder in enumerate(placeholders):
        s = s.replace(f"\x00PLACEHOLDER_{index}\x00", placeholder)
    return s
