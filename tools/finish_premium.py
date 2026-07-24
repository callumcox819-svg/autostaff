"""Final pass: html_emoji in messages + toast() for callback.answer."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

HANDLERS = list((ROOT / "handlers").rglob("*.py"))
SERVICES = [
    ROOT / "services" / n
    for n in (
        "incoming_mail_worker.py",
        "mailing_proxy_health.py",
        "smtp_block_control.py",
        "smtp_proxy_send.py",
    )
]
TARGETS = HANDLERS + [p for p in SERVICES if p.is_file()]

IMPORT = (
    "from utils.ui_emoji import html_emoji, menu_path, toast, "
    "msg_fail, msg_ok, msg_wait, msg_warn\n"
)

EMOJI_KEYS: list[tuple[str, str]] = [
    ("⚡️", "burst"),
    ("✉️", "mail"),
    ("✏️", "edit"),
    ("⬅️", "back"),
    ("🗑️", "delete"),
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
    ("📎", "presets"),
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
    ("⏹", "stop"),
    ("🧩", "puzzle"),
]

SKIP_LINE = (
    '"""',
    "'''",
    "F.text",
    "in_({",
    "startswith(",
    "# Email reply",
    "IMPORTANT (",
    " if getattr",
    "labels.get",
)


def _has_emoji(s: str) -> bool:
    return any(u in s for u, _ in EMOJI_KEYS)


def _emoji_key_for_toast(body: str) -> tuple[str, str] | None:
    b = body.strip()
    for uni, key in EMOJI_KEYS:
        if b.startswith(uni):
            return key, b[len(uni) :].strip()
        if b.endswith(uni):
            return key, b[: -len(uni)].strip()
    return None


def _convert_html_body(body: str) -> str:
    out = body
    for uni, key in EMOJI_KEYS:
        out = out.replace(uni, "{html_emoji('" + key + "')}")
    return out


def _process_callback_toast(line: str) -> str:
    if "callback.answer(" not in line or "toast(" in line:
        return line

    def repl(m: re.Match[str]) -> str:
        inner = m.group(1)
        if not _has_emoji(inner):
            return m.group(0)
        parsed = _emoji_key_for_toast(inner)
        if not parsed:
            return m.group(0)
        key, rest = parsed
        esc = rest.replace('"', '\\"')
        return f'callback.answer(toast("{key}", "{esc}")'

    return re.sub(r"callback\.answer\(\s*\"([^\"]*)\"", repl, line)


def _process_html_strings(line: str) -> str:
    if "html_emoji(" in line or "<tg-emoji" in line:
        return line
    if line.strip().startswith("#"):
        return line
    if any(x in line for x in SKIP_LINE):
        return line
    if "F.text" in line or "in_({" in line:
        return line
    if not _has_emoji(line):
        return line

    def repl(m: re.Match[str]) -> str:
        body = m.group(1)
        if not _has_emoji(body) or "html_emoji(" in body:
            return m.group(0)
        new_body = _convert_html_body(body)
        esc = new_body.replace('"', '\\"')
        return f'f"{esc}"'

    return re.sub(r'f?"([^"\\]*(?:\\.[^"\\]*)*)"', repl, line)


def _process_line(line: str) -> str:
    line = _process_callback_toast(line)
    line = _process_html_strings(line)
    return line


def _ensure_import(text: str) -> str:
    needs = "html_emoji(" in text or "toast(" in text or "msg_ok(" in text
    if not needs:
        return text
    if "from utils.ui_emoji import" in text:
        if "toast" not in text or "msg_ok" not in text:
            text = re.sub(
                r"from utils\.ui_emoji import [^\n]+",
                "from utils.ui_emoji import html_emoji, inline_button, menu_path, toast, "
                "msg_fail, msg_ok, msg_wait, msg_warn",
                text,
                count=1,
            )
        return text
    m = re.search(r"^(from .+\n)+", text, re.M)
    if not m:
        return IMPORT + text
    return text[: m.end()] + IMPORT + text[m.end() :]


def main() -> None:
    n = 0
    for p in sorted(set(TARGETS)):
        if p.name == "ui_emoji.py":
            continue
        raw = p.read_text(encoding="utf-8")
        lines = raw.splitlines(keepends=True)
        out = "".join(_process_line(ln) for ln in lines)
        out = _ensure_import(out)
        if out != raw:
            p.write_text(out, encoding="utf-8")
            n += 1
            print(p.relative_to(ROOT))
    print("updated", n)


if __name__ == "__main__":
    main()
