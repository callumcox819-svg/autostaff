"""Safe line-by-line premium emoji for .answer / .edit_text / send_message / caption=."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGETS = list((ROOT / "handlers").rglob("*.py")) + [
    ROOT / "services" / "incoming_mail_worker.py",
    ROOT / "services" / "aqua_network.py",
    ROOT / "middlewares" / "bot_access.py",
]

# Lines assigning message text (multi-line friendly single-line tails)
TEXT_MARK = (
    "text = ",
    "title = ",
    "footer = ",
    "lines = [",
    "lines.append(",
    "run_line = ",
)

IMPORT = (
    "from utils.ui_emoji import html_emoji, menu_path, "
    "msg_fail, msg_ok, msg_wait, msg_warn\n"
)

EMOJI_KEYS: list[tuple[str, str]] = [
    ("⚡️", "burst"),
    ("✉️", "mail"),
    ("✏️", "edit"),
    ("ℹ️", "info"),
    ("👑", "admin"),
    ("🧪", "test_mail"),
    ("🧾", "profile"),
    ("📣", "burst"),
    ("📬", "email"),
    ("📮", "email"),
    ("📊", "status"),
    ("📄", "presets"),
    ("📧", "email"),
    ("📨", "mail"),
    ("🔗", "link"),
    ("💶", "price"),
    ("👤", "user"),
    ("⚠️", "warn"),
    ("⛔", "deny"),
    ("✅", "ok"),
    ("❌", "fail"),
    ("⏳", "wait"),
    ("⚡", "burst"),
    ("🔄", "refresh"),
    ("🟢", "green"),
    ("🟡", "yellow"),
    ("🔴", "red"),
    ("🗑", "delete"),
    ("↩️", "restore"),
    ("⌨️", "write"),
    ("📝", "write"),
    ("▶️", "send"),
    ("🔒", "key"),
    ("➕", "add"),
    ("🚫", "cancel"),
]

API_MARK = (
    ".answer(",
    ".edit_text(",
    "send_message(",
    "caption=",
    "ACCESS_DENIED_TEXT",
    "raise AquaError(",
    "callback.answer(",
)

SKIP_MARK = (
    '"""',
    "'''",
    "F.text",
    "in_({",
    "startswith(",
    "def _",
    "# Email reply",
    "IMPORTANT (",
)


def _has_emoji(s: str) -> bool:
    return any(u in s for u, _ in EMOJI_KEYS)


def _convert_body(body: str) -> str:
    out = body
    for uni, key in EMOJI_KEYS:
        out = out.replace(uni, "{html_emoji('" + key + "')}")
    return out


def _process_line(line: str) -> str:
    if "html_emoji(" in line or "<tg-emoji" in line:
        return line
    stripped = line.strip()
    if stripped.startswith("#") or stripped.startswith('"""') or stripped.startswith("'''"):
        return line
    if any(m in line for m in SKIP_MARK):
        return line
    if not _has_emoji(line):
        return line
    # Не трогаем триггеры клавиатуры и фильтры
    if "F.text" in line or "in_({" in line:
        return line
    if " if getattr" in line or "labels.get" in line:
        return line

    def repl(m: re.Match[str]) -> str:
        prefix, _quote, body = m.group(1), m.group(2), m.group(3)
        if not _has_emoji(body) or "html_emoji(" in body:
            return m.group(0)
        new_body = _convert_body(body)
        esc = new_body.replace('"', '\\"')
        return f'f"{esc}"'

    line2 = re.sub(r'(\bf?)(")([^"]*)"', repl, line)
    return line2


def _ensure_import(text: str) -> str:
    if "html_emoji(" not in text:
        return text
    if "from utils.ui_emoji import" in text:
        if "msg_ok" not in text:
            text = re.sub(
                r"from utils\.ui_emoji import [^\n]+",
                "from utils.ui_emoji import html_emoji, inline_button, menu_path, "
                "msg_fail, msg_ok, msg_wait, msg_warn",
                text,
                count=1,
            )
        return text
    m = re.search(r"^(from .+\n)+", text, re.M)
    if not m:
        return IMPORT + text
    return text[: m.end()] + IMPORT + text[m.end() :]


def process_file(path: Path) -> bool:
    if path.name == "ui_emoji.py":
        return False
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    out = [_process_line(ln) for ln in lines]
    text = "".join(out)
    text = _ensure_import(text)
    raw = path.read_text(encoding="utf-8")
    if text == raw:
        return False
    path.write_text(text, encoding="utf-8")
    return True


def main() -> None:
    n = 0
    for p in sorted(set(TARGETS)):
        if not p.is_file():
            continue
        if process_file(p):
            n += 1
            print(p.relative_to(ROOT))
    print("done", n)


if __name__ == "__main__":
    main()
