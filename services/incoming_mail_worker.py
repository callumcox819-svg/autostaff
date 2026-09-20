# services/incoming_mail_worker.py
from __future__ import annotations

import asyncio
import email
import hashlib
import html
import html as html_module
import imaplib
import logging
import re
import select as pyselect
import threading
import time
from contextlib import asynccontextmanager
from email.header import decode_header
from email.utils import parseaddr
from typing import Optional, List, Tuple, Dict, Any

from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from utils.ui_emoji import html_emoji, inline_button, menu_path, toast, msg_fail, msg_ok, msg_wait, msg_warn
from sqlalchemy import select as sa_select, or_ as sa_or, func, update
from sqlalchemy.exc import OperationalError

from database import Session
from models import EmailAccount, User, ConversationLink, Offer, OfferEmail, IncomingMail
from services.link_id import link_id_from_generated_url
from services.user_settings import get_user_setting

logger = logging.getLogger(__name__)

IMAP_DIAG_DB_KEY = "imap_worker_diag_v1"
_DIAG_PERSIST_INTERVAL_SEC = 45
_last_diag_persist_at: float = 0.0

# ---- CONFIG ----
USE_IMAP_IDLE = False              # только round-robin polling (не поток на ящик)
IDLE_TIMEOUT_SEC = 60
POLL_FALLBACK_SEC = 20
DEFAULT_MAX_PER_ACCOUNT = 10

_os = __import__("os")
def _imap_int_env(name: str, default: str, *, lo: int, hi: int) -> int:
    raw = (_os.getenv(name) or default).strip()
    try:
        v = int(float(raw))
    except (TypeError, ValueError):
        v = int(default)
    return max(lo, min(hi, v))


IMAP_CONNECT_TIMEOUT_SEC = _imap_int_env("IMAP_CONNECT_TIMEOUT_SEC", "12", lo=5, hi=20)
IMAP_ACCOUNT_TIMEOUT_SEC = _imap_int_env("IMAP_ACCOUNT_TIMEOUT_SEC", "22", lo=10, hi=35)
# Жёсткий потолок 40с — старый Railway 120с глотал ответы.
IMAP_PER_ACCOUNT_INTERVAL_SEC = _imap_int_env(
    "IMAP_PER_ACCOUNT_INTERVAL_SEC",
    _os.getenv("INCOMING_MAIL_POLL_SECONDS", "35") or "35",
    lo=20,
    hi=40,
)
IMAP_CYCLE_SLEEP_SEC = _imap_int_env("IMAP_CYCLE_SLEEP_SEC", "2", lo=1, hi=5)

# ---- STATE ----
_worker_task: asyncio.Task | None = None
LAST_UID: Dict[int, int] = {}
_NOTIFY_ONCE: set[str] = set()

_ERROR_STREAK: Dict[int, int] = {}
_BACKOFF_UNTIL: Dict[int, float] = {}
_LAST_POLL_AT: Dict[int, float] = {}
_SCHEDULER_LAST_TICK: float = 0.0

_LAST_EOF_LOG: Dict[int, float] = {}
_EOF_LOG_COOLDOWN_SEC = 120.0

FULL_BODIES: Dict[tuple[int, str], str] = {}
FULL_META: Dict[tuple[int, str], Dict[str, Any]] = {}


def _uid_lookup_keys(uid: str) -> list[str]:
    u = (uid or "").strip()
    keys: list[str] = []
    if u:
        keys.append(u)
    if ":" in u:
        tail = u.rsplit(":", 1)[-1].strip()
        if tail and tail not in keys:
            keys.append(tail)
    elif u:
        keys.append(f"S:{u}")
    return keys


def full_meta_get(acc_id: int, uid: str) -> Dict[str, Any] | None:
    for k in _uid_lookup_keys(uid):
        m = FULL_META.get((int(acc_id), str(k)))
        if m:
            return m
    return None


def full_body_get(acc_id: int, uid: str) -> str:
    for k in _uid_lookup_keys(uid):
        b = FULL_BODIES.get((int(acc_id), str(k)))
        if b:
            return b
    return ""


@asynccontextmanager
async def _imap_db_session():
    """Короткий доступ к Postgres со сбросом SOCKS-патча (не держим lock на всю обработку письма)."""
    from proxy_manager import database_socket_guard

    async with database_socket_guard():
        async with Session() as session:
            yield session


def _now() -> float:
    return time.time()


def _e(s: str) -> str:
    return html.escape(s or "")


def _normalize_subject(subject: str) -> str:
    """Тема для сопоставления с оффером (GMX spam и т.п.)."""
    s = (subject or "").strip().lower()
    for prefix in ("re:", "fwd:", "fw:", "aw:", "wg:"):
        while s.startswith(prefix):
            s = s[len(prefix) :].strip()
    return re.sub(r"\s+", " ", s).strip()


def _canon_email(email: str) -> str:
    e = (email or "").strip().lower()
    if "@" not in e:
        return e
    local, domain = e.split("@", 1)
    local = local.strip()
    domain = domain.strip().lower()
    if "+" in local:
        local = local.split("+", 1)[0]
    if domain in ("googlemail.com", "gmail.com"):
        local = local.replace(".", "")
        domain = "gmail.com"
    return f"{local}@{domain}"


def _calc_backoff(streak: int) -> int:
    """Короткий backoff: длинный 60с+ после Gmail flood — ответы пропадают."""
    if streak <= 1:
        return 2
    if streak == 2:
        return 4
    if streak == 3:
        return 8
    return 15


def _is_invalid_credentials_error(e: Exception) -> bool:
    s = str(e).lower()
    return "authentication failed" in s or "invalid credentials" in s or "web login required" in s


def _is_transient_ssl_eof(e: Exception) -> bool:
    s = str(e).lower()
    return "eof occurred" in s or "connection reset" in s or ("ssl" in s and "eof" in s)


def _looks_like_spam(from_email: str, from_name: str, subject: str, body: str) -> bool:
    f = (from_email or "").strip().lower()
    name = (from_name or "").strip().lower()
    subj = (subject or "").strip().lower()
    body_l = (body or "").strip().lower()
    if not f or "@" not in f:
        return False
    local, domain = f.split("@", 1)
    domain = domain.strip().lower()
    if local.startswith("enews") or local.startswith("newsletter"):
        return True
    if domain.startswith("em.") and "linkedin" in domain:
        return True
    if "uniqlo" in domain or "uniqlo" in name:
        return True
    if "skillsture" in domain or "skillsture" in name:
        return True
    if "linkedin" in domain and "premium" in name:
        return True
    marketing_domains = (
        ".my.uniqlo.com",
        "skillsture.io",
        "peoplelogy",
        "tally.so",
    )
    if any(x in domain or x in f for x in marketing_domains):
        return True
    if "list-unsubscribe" in body_l or "utm_campaign=" in body_l:
        if "ricardo.ch" not in body_l and "tutti.ch" not in body_l:
            return True
    if subj and any(
        p in subj
        for p in (
            "unsubscribe",
            "newsletter",
            "limited offer",
            "shop your favourite",
            "valued member",
            "burnout",
        )
    ):
        if not subj.startswith("re:") and not subj.startswith("aw:"):
            return True
    return False


_NOREPLY_LOCAL_RE = re.compile(
    r"^(?:no[-_.]?reply|noreply|donotreply|do[-_.]?not[-_.]?reply|noresponse|no[-_.]?response)(?:\+.*)?$",
    re.IGNORECASE,
)


def _is_noreply_automated_sender(from_email: str) -> bool:
    """no-reply@* (Instagram, маркетплейсы) — не показываем карточки; продавцы не трогаем."""
    f = (from_email or "").strip().lower()
    if not f or "@" not in f:
        return False
    if _is_mailer_daemon_notice(f, ""):
        return False
    local = f.split("@", 1)[0]
    return bool(_NOREPLY_LOCAL_RE.match(local))


_APPLE_SYSTEM_DOMAINS = frozenset(
    {
        "id.apple.com",
        "email.apple.com",
        "insideapple.apple.com",
        "gs.apple.com",
    }
)


# Авто-уведомления чужих площадок (не ricardo/tutti) — не ответы продавцов.
_PLATFORM_SYSTEM_DOMAINS = frozenset(
    {
        "wallapop.com",
        "mail.wallapop.com",
        "vinted.com",
        "mail.vinted.com",
        "leboncoin.fr",
        "subito.it",
        "marktplaats.nl",
        "mail.instagram.com",
        # Только системная почта Meta (коды/уведомления), не *.facebook.com целиком.
        "facebookmail.com",
        "account.tiktok.com",
        "tiktok.com",
    }
)
_PLATFORM_SYSTEM_NAME_HINTS = frozenset(
    {
        "wallapop",
        "vinted",
        "instagram",
        "tiktok",
        "leboncoin",
        "subito",
        "marktplaats",
    }
)

_AMAZON_DOMAIN_RE = re.compile(
    r"^(?:[a-z0-9-]+\.)*amazon\.(?:"
    r"com|co\.jp|de|fr|co\.uk|es|it|ca|com\.au|in|nl|se|be|pl|"
    r"sa|sg|com\.mx|com\.br|ae|eg"
    r")(?:\.[a-z]{2,})?$",
    re.IGNORECASE,
)


def _is_amazon_system_domain(domain: str) -> bool:
    """account-update@amazon.co.jp и др. — не ответы продавцов ricardo/tutti."""
    d = (domain or "").strip().lower()
    if not d:
        return False
    if _AMAZON_DOMAIN_RE.match(d):
        return True
    return d.endswith(".amazon.com") or d.endswith(".amazon.co.jp")


def _is_snapchat_system_domain(domain: str) -> bool:
    d = (domain or "").strip().lower()
    return bool(d) and (d == "snapchat.com" or d.endswith(".snapchat.com"))


def _is_alibaba_system_domain(domain: str) -> bool:
    d = (domain or "").strip().lower()
    if not d:
        return False
    if d == "alibaba.com" or d.endswith(".alibaba.com"):
        return True
    return d == "alibaba-inc.com" or d.endswith(".alibaba-inc.com")


def _is_platform_system_mail(from_email: str, from_name: str, subject: str = "") -> bool:
    """Коды верификации / уведомления маркетплейсов (Wallapop и т.д.)."""
    f = (from_email or "").strip().lower()
    if _is_mailer_daemon_notice(f, subject or ""):
        return False
    if not f or "@" not in f:
        return False
    _local, _, domain = f.rpartition("@")
    if domain in _PLATFORM_SYSTEM_DOMAINS:
        return True
    for plat in ("wallapop", "vinted", "instagram", "tiktok"):
        if domain == f"{plat}.com" or domain.endswith(f".{plat}.com"):
            return True
    # Facebook: только facebookmail.com (коды/системка), не весь facebook.com
    if domain == "facebookmail.com" or domain.endswith(".facebookmail.com"):
        return True
    name = (from_name or "").strip().lower()
    if name in _PLATFORM_SYSTEM_NAME_HINTS:
        root = domain.split(".")[-2] if "." in domain else domain
        if root in _PLATFORM_SYSTEM_NAME_HINTS or name in domain:
            return True
    if name == "facebook" and (domain == "facebookmail.com" or domain.endswith(".facebookmail.com")):
        return True
    if _is_amazon_system_domain(domain):
        return True
    name_compact = name.replace(" ", "")
    if "amazon" in name_compact and _is_amazon_system_domain(domain):
        return True
    if _is_snapchat_system_domain(domain):
        return True
    if "snapchat" in name_compact and _is_snapchat_system_domain(domain):
        return True
    if _is_alibaba_system_domain(domain):
        return True
    if "alibaba" in name_compact and _is_alibaba_system_domain(domain):
        return True
    return False


def _is_apple_system_mail(from_email: str, from_name: str, subject: str = "") -> bool:
    """Apple ID / верификация аккаунта — не карточки продавцов."""
    f = (from_email or "").strip().lower()
    if _is_mailer_daemon_notice(f, subject or ""):
        return False
    if not f or "@" not in f:
        return False
    local, _, domain = f.rpartition("@")
    if domain in _APPLE_SYSTEM_DOMAINS:
        return True
    if domain == "apple.com" and local in ("appleid", "no-reply", "noreply"):
        return True
    name = (from_name or "").strip().lower()
    if name == "apple" and (domain in _APPLE_SYSTEM_DOMAINS or domain.endswith(".apple.com")):
        return True
    return False


def _is_automated_system_sender(from_email: str, from_name: str = "", subject: str = "") -> bool:
    """Системные авто-письма (no-reply, Apple, Wallapop…) — без карточек в TG."""
    return (
        _is_noreply_automated_sender(from_email)
        or _is_apple_system_mail(from_email, from_name, subject)
        or _is_platform_system_mail(from_email, from_name, subject)
    )


def _is_google_system_mail(from_email: str, from_name: str, subject: str) -> bool:
    """Системные письма Google (безопасность, уведомления) — в Telegram не шлём."""
    f = (from_email or "").strip().lower()
    name = (from_name or "").strip().lower()
    subj = (subject or "").strip().lower()
    if _is_mailer_daemon_notice(f, subject or ""):
        return False
    if name == "google":
        return True
    if not f or "@" not in f:
        return False
    local, _, domain = f.rpartition("@")
    if domain in ("google.com", "accounts.google.com", "googlemail.com"):
        return True
    if domain.endswith(".google.com"):
        return True
    if "accounts.google" in domain:
        return True
    if domain == "google.com" and local in (
        "no-reply",
        "noreply",
        "mail-noreply",
        "notification",
        "notifications",
    ):
        return True
    if "keamanan" in subj or "security" in subj and "google" in f:
        return True
    return False


def _extract_ad_link(text: str) -> str | None:
    if not text:
        return None
    m = re.search(r"(https?://[^\s<>\"']+)", text)
    if not m:
        return None
    return m.group(1).strip()


def _is_mailer_daemon_notice(from_email: str, subject: str) -> bool:
    """DSN / mailer-daemon — показываем в TG (не путать с noreply@google.com)."""
    f = (from_email or "").strip().lower()
    if "mailer-daemon" in f or "postmaster" in f:
        return True
    s = (subject or "").strip().lower()
    return "delivery status notification" in s


def _is_recipient_delivery_failure_bounce(subject: str, body: str) -> bool:
    from services.bounce_recipient import is_recipient_delivery_failure_bounce

    return is_recipient_delivery_failure_bounce(subject, body)


def _is_smtp_block_bounce(from_email: str, subject: str, body: str) -> bool:
    """Gmail block отправителя (любой язык) — снимаем ящик с SMTP, IMAP оставляем."""
    from services.smtp_block_control import is_gmail_sender_block_text

    if not is_gmail_sender_block_text(subject, body):
        return False
    f = (from_email or "").lower()
    s = (subject or "").lower()
    if "mailer-daemon" in f or "postmaster" in f:
        return True
    if "delivery status notification" in s:
        return True
    return "message blocked" in s or "pesan diblokir" in s


def _truthy(v: str | None) -> bool:
    s = (v or "").strip().lower()
    return s in {"1", "true", "yes", "on", "y"}


async def _notify_once(bot: Bot, chat_id: int, *, key: str, text: str) -> None:
    if key in _NOTIFY_ONCE:
        return
    _NOTIFY_ONCE.add(key)
    try:
        await bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")
    except Exception:
        pass


async def _db_commit_retry(session, attempts: int = 3) -> None:
    last = None
    for _ in range(attempts):
        try:
            await session.commit()
            return
        except OperationalError as e:
            last = e
            await asyncio.sleep(0.2)
    if last:
        raise last


async def _set_last_seen_uid(acc_id: int, uid: int) -> None:
    try:
        async with _imap_db_session() as session:
            acc = (
                await session.execute(
                    sa_select(EmailAccount).where(EmailAccount.id == int(acc_id)).limit(1)
                )
            ).scalars().first()
            if acc:
                acc.last_seen_uid = int(uid)
                await _db_commit_retry(session)
    except Exception:
        logger.exception("Failed to persist last_seen_uid for acc_id=%s", acc_id)


async def _upsert_convlink(
    *,
    user_id: int,
    inbox_email: str,
    contact_email: str,
    ad_url: str | None = None,
    generated_link: str | None = None,
    tg_message_id: int | None = None,
    pinned_offer_id: int | None = None,
    pinned_outgoing_subject: str | None = None,
) -> None:
    inbox = _canon_email(inbox_email)
    contact = _canon_email(contact_email)
    if not inbox or not contact:
        return

    try:
        async with _imap_db_session() as session:
            row = (await session.execute(
                sa_select(ConversationLink).where(
                    ConversationLink.user_id == int(user_id),
                    func.lower(ConversationLink.account_email) == inbox,
                    func.lower(ConversationLink.from_email) == contact,
                )
            )).scalars().first()

            if row is None:
                row = ConversationLink(
                    user_id=int(user_id),
                    account_email=inbox,
                    from_email=contact,
                    ad_url=(ad_url or None),
                    generated_link=(generated_link or None),
                    tg_message_id=int(tg_message_id) if tg_message_id is not None else None,
                    pinned_offer_id=int(pinned_offer_id) if pinned_offer_id else None,
                    pinned_outgoing_subject=(
                        (pinned_outgoing_subject or "").strip()[:500] or None
                    ),
                )
                session.add(row)
            else:
                if ad_url:
                    row.ad_url = ad_url
                if generated_link:
                    row.generated_link = generated_link
                if pinned_offer_id:
                    row.pinned_offer_id = int(pinned_offer_id)
                ps = (pinned_outgoing_subject or "").strip()[:500]
                if ps:
                    row.pinned_outgoing_subject = ps
                # Anchor = первое TG-сообщение диалога; повторные письма не перезаписывают.
                if tg_message_id is not None and row.tg_message_id is None:
                    row.tg_message_id = int(tg_message_id)

            await _db_commit_retry(session)
    except Exception:
        logger.exception("Failed to upsert conversation_links")


async def _load_convlink(
    *,
    user_id: int,
    inbox_email: str,
    contact_email: str,
) -> ConversationLink | None:
    inbox = _canon_email(inbox_email)
    contact = _canon_email(contact_email)
    if not inbox or not contact:
        return None
    try:
        async with _imap_db_session() as session:
            row = (await session.execute(
                sa_select(ConversationLink).where(
                    ConversationLink.user_id == int(user_id),
                    func.lower(ConversationLink.account_email) == inbox,
                    func.lower(ConversationLink.from_email) == contact,
                )
            )).scalars().first()
            return row
    except Exception:
        logger.exception("Failed to load conversation_links")
        return None


def _imap_connect(provider: str, email_addr: str) -> tuple[str, int]:
    """Хост IMAP по домену (как при добавлении аккаунта в handlers/accounts.py)."""
    try:
        from handlers.accounts import detect_imap_server

        host, _prov = detect_imap_server((email_addr or "").strip())
        if host:
            return host, 993
    except Exception:
        pass
    p = (provider or "").strip().lower()
    if p == "gmx":
        return "imap.gmx.net", 993
    if p == "icloud":
        return "imap.mail.me.com", 993
    return "imap.gmail.com", 993


def _find_all_mailbox_name(M: imaplib.IMAP4_SSL) -> str | None:
    try:
        typ, data = M.list()
        if typ != "OK" or not data:
            return None

        candidates: list[str] = []
        for raw in data:
            if not raw:
                continue
            if isinstance(raw, bytes):
                line = raw.decode("utf-8", "ignore")
            else:
                line = str(raw)

            low = line.lower()
            m = re.findall(r'"([^"]+)"', line)
            name = m[-1] if m else line.split()[-1].strip('"')

            if (
                "\\all" in low
                or "all mail" in low
                or "alle nachrichten" in low
                or "todas as mensagens" in low
                or "tutti i messaggi" in low
            ):
                candidates.append(name)

        for p in ("[Gmail]/All Mail", "[Google Mail]/All Mail"):
            if p in candidates:
                return p

        return candidates[0] if candidates else None
    except Exception:
        return None


async def is_inbound_from_mailed_seller(
    session,
    user_id: int,
    from_email: str,
) -> bool:
    """
    В бот пускаем только продавцов, которым уходила рассылка (/send|тест) у этого user.
    Левые письма на ящик — не в TG и не в IncomingMail.
    """
    from services.mailing_send_log import has_mailing_send_for_contact
    from services.email_blacklist import is_email_already_sent
    from services.offer_storage import normalize_incoming_seller_email

    fe = normalize_incoming_seller_email(from_email) or (from_email or "").strip().lower()
    if not fe or "@" not in fe or not user_id:
        return False
    if await has_mailing_send_for_contact(session, int(user_id), fe):
        return True
    if await is_email_already_sent(session, int(user_id), fe):
        return True
    from sqlalchemy import func as sa_func

    conv = (
        await session.execute(
            sa_select(ConversationLink.id)
            .where(ConversationLink.user_id == int(user_id))
            .where(sa_func.lower(ConversationLink.from_email) == fe)
            .limit(1)
        )
    ).scalar_one_or_none()
    if conv is not None:
        return True
    mail_hit = (
        await session.execute(
            sa_select(IncomingMail.id)
            .where(IncomingMail.user_id == int(user_id))
            .where(sa_func.lower(IncomingMail.from_email) == fe)
            .limit(1)
        )
    ).scalar_one_or_none()
    if mail_hit is not None:
        return True
    oe = (
        await session.execute(
            sa_select(OfferEmail.id)
            .join(Offer, Offer.id == OfferEmail.offer_id)
            .where(Offer.user_id == int(user_id))
            .where(sa_func.lower(OfferEmail.email) == fe)
            .limit(1)
        )
    ).scalar_one_or_none()
    return oe is not None


def _find_spam_mailbox_name(M: imaplib.IMAP4_SSL) -> str | None:
    """Spam/Junk: Gmail `[Gmail]/Spam`, GMX Spam/Junk, и т.п."""
    hardcoded = (
        "[Gmail]/Spam",
        "[Google Mail]/Spam",
        "Spam",
        "Junk",
        "SPAM",
        "JUNK",
        "INBOX.Spam",
        "INBOX.Junk",
    )
    try:
        typ, data = M.list()
        names: list[str] = []
        if typ == "OK" and data:
            for raw in data:
                if not raw:
                    continue
                line = raw.decode("utf-8", "ignore") if isinstance(raw, bytes) else str(raw)
                low = line.lower()
                m = re.findall(r'"([^"]+)"', line)
                name = m[-1] if m else line.split()[-1].strip('"')
                if not name:
                    continue
                if (
                    "\\junk" in low
                    or "\\spam" in low
                    or "spam" in low
                    or "junk" in low
                    or "undesirable" in low
                    or "junk-e-mail" in low
                ):
                    names.append(name)
        for p in hardcoded:
            if p in names:
                return p
        for p in hardcoded:
            try:
                typ_sel, _ = M.select(p, readonly=True)
                if typ_sel == "OK":
                    try:
                        M.select("INBOX")
                    except Exception:
                        pass
                    return p
            except Exception:
                continue
        return names[0] if names else None
    except Exception:
        return None


async def _spam_mail_allowed_for_user(
    session,
    *,
    user_id: int,
    account_id: int,
    from_email: str,
    subject: str,
) -> bool:
    """Из Spam — только продавцы с рассылкой у этого user."""
    _ = account_id, subject
    return await is_inbound_from_mailed_seller(session, int(user_id), from_email)


_SKIP_MAILBOX_SUBSTR = (
    "draft",
    "sent",
    "trash",
    "bin",
    "deleted",
    "junk",
    "spam",
    "all mail",
    "alle nachrichten",
    "important",
    "starred",
    "flagged",
    "chats",
    "scheduled",
    "snoozed",
    "outbox",
    "archive",
)


def _list_extra_watch_mailboxes(M: imaplib.IMAP4_SSL, *, spam_box: str | None) -> list[str]:
    """Доп. папки кроме INBOX/Spam: UNSEEN (не Sent/Trash/All Mail)."""
    out: list[str] = []
    spam_l = (spam_box or "").strip().lower()
    try:
        typ, data = M.list()
        if typ != "OK" or not data:
            return out
        for raw in data:
            if not raw:
                continue
            line = raw.decode("utf-8", "ignore") if isinstance(raw, bytes) else str(raw)
            low = line.lower()
            if "\\noselect" in low:
                continue
            m = re.findall(r'"([^"]+)"', line)
            name = m[-1] if m else line.split()[-1].strip('"')
            if not name:
                continue
            nl = name.lower().replace("\\", "/")
            if nl == "inbox" or nl.endswith("/inbox"):
                continue
            if spam_l and nl == spam_l:
                continue
            if any(s in nl for s in _SKIP_MAILBOX_SUBSTR):
                continue
            out.append(name)
    except Exception:
        logger.exception("IMAP LIST mailboxes failed")
    return out[:12]


def _imap_connect_and_select(host: str, port: int, email_addr: str, password: str) -> imaplib.IMAP4_SSL:
    M = imaplib.IMAP4_SSL(host, port, timeout=IMAP_CONNECT_TIMEOUT_SEC)
    M.login(email_addr, password)

    typ, _ = M.select("INBOX")
    if typ != "OK":
        raise RuntimeError("IMAP select INBOX failed")

    return M


def _imap_supports_idle(M: imaplib.IMAP4_SSL) -> bool:
    try:
        caps = M.capabilities or ()
        return b"IDLE" in caps or "IDLE" in caps
    except Exception:
        return False


def _imap_idle_wait_sync(M: imaplib.IMAP4_SSL, timeout_sec: int) -> None:
    try:
        tag = M._new_tag()
        M.send(f"{tag} IDLE\r\n".encode())
        end = time.time() + float(timeout_sec)
        while time.time() < end:
            r, _, _ = pyselect.select([M.socket()], [], [], 1)
            if r:
                data = M.readline()
                if not data:
                    break
        M.send(b"DONE\r\n")
        M.readline()
    except Exception:
        pass


def _decode_mime_words(s: str) -> str:
    if not s:
        return ""
    try:
        parts = decode_header(s)
        out = []
        for t, enc in parts:
            if isinstance(t, bytes):
                out.append(t.decode(enc or "utf-8", errors="ignore"))
            else:
                out.append(t)
        return "".join(out)
    except Exception:
        return s


def _decode_part_text(part: email.message.Message) -> str:
    payload = part.get_payload(decode=True) or b""
    charset = part.get_content_charset() or "utf-8"
    try:
        return payload.decode(charset, errors="ignore")
    except Exception:
        return payload.decode("utf-8", errors="ignore")


def _extract_text_from_msg(msg: email.message.Message) -> str:
    """Один текст: text/plain предпочтительнее HTML (иначе Gmail дублирует ответ+цитату)."""
    plains: list[str] = []
    htmls: list[str] = []
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_maintype() == "multipart":
                continue
            disp = (part.get("Content-Disposition") or "").lower()
            if "attachment" in disp:
                continue
            ctype = part.get_content_type()
            txt = _decode_part_text(part)
            if ctype == "text/plain":
                plains.append(txt)
            elif ctype == "text/html":
                htmls.append(txt)
    else:
        ctype = msg.get_content_type()
        txt = _decode_part_text(msg)
        if ctype == "text/html":
            htmls.append(txt)
        else:
            plains.append(txt)
    if plains:
        return "\n\n".join(p.strip() for p in plains if p.strip()).strip()
    if htmls:
        return _strip_html_to_text("\n\n".join(htmls)).strip()
    return ""


def _imap_fetch_new_sync_raw(
    *,
    host: str,
    port: int,
    email_addr: str,
    password: str,
    last_uid: Optional[int],
) -> tuple[List[Tuple[str, str, str, str, str, str, str]], Optional[int]]:
    """Fetch new mails from INBOX + Spam/Junk + other folders (not Sent/Trash/All).

    - INBOX: uses UID > last_uid (first run returns empty and sets last_uid=max_uid).
    - Spam/Junk and other folders: UNSEEN only, mark \\Seen; uid prefixes S: / Xn:.
    - TG/DB whitelist (mailed sellers) is applied in the async processor.

    Each mail tuple: (uid, from_email, from_name, subject, date_str, body,
                      rfc_message_id, rfc_in_reply_to, rfc_references)
    """
    M = None

    def _fetch_uids(uids_list: list[int], *, uid_prefix: str = "") -> list:
        out = []
        for uid in uids_list:
            typ2, msg_data = M.uid("fetch", str(uid), "(RFC822)")
            if typ2 != "OK" or not msg_data:
                continue

            raw = None
            for item in msg_data:
                if isinstance(item, tuple) and item[1]:
                    raw = item[1]
                    break
            if not raw:
                continue

            msg = email.message_from_bytes(raw)

            from_raw = _decode_mime_words(msg.get("From", ""))
            subject = _decode_mime_words(msg.get("Subject", ""))
            date_str = msg.get("Date", "") or ""
            from email.header import decode_header
            from services.email_threading import normalize_rfc_message_id

            def _hdr(name: str) -> str:
                raw_h = msg.get(name) or msg.get(name.title()) or ""
                if not raw_h:
                    return ""
                parts = decode_header(raw_h)
                out = []
                for frag, enc in parts:
                    if isinstance(frag, bytes):
                        out.append(frag.decode(enc or "utf-8", "replace"))
                    else:
                        out.append(str(frag))
                return "".join(out)

            rfc_message_id = normalize_rfc_message_id(_hdr("Message-ID") or _hdr("Message-Id")) or ""
            rfc_in_reply_to = normalize_rfc_message_id(_hdr("In-Reply-To")) or ""
            rfc_references = (_hdr("References") or "").strip()

            name, addr = parseaddr(from_raw)
            from_email = (addr or "").strip().lower()
            from_name = (name or "").strip()
            from services.offer_storage import normalize_incoming_seller_email

            from_email = normalize_incoming_seller_email(from_email) or from_email

            body = _extract_text_from_msg(msg)

            out.append(
                (
                    f"{uid_prefix}{uid}",
                    from_email,
                    from_name,
                    subject,
                    date_str,
                    body,
                    rfc_message_id,
                    rfc_in_reply_to,
                    rfc_references,
                )
            )
        return out

    try:
        M = _imap_connect_and_select(host, port, email_addr, password)

        # --- INBOX ---
        typ, data = M.uid("search", None, "ALL")
        if typ != "OK":
            inbox_uids = []
        else:
            inbox_uids = []
            if data and data[0]:
                inbox_uids = [int(x) for x in data[0].split() if x.isdigit()]

        inbox_mails: list = []
        max_uid = last_uid

        if inbox_uids:
            max_uid = max(inbox_uids)

            # first run: don't forward old inbox mails
            if last_uid is None:
                inbox_new_uids = []
            else:
                inbox_new_uids = [u for u in inbox_uids if u > int(last_uid)]
                if inbox_new_uids:
                    inbox_mails = _fetch_uids(sorted(inbox_new_uids)[-DEFAULT_MAX_PER_ACCOUNT:])
        else:
            inbox_new_uids = []

        updated_last_uid: Optional[int] = int(max_uid) if max_uid is not None else last_uid
        if last_uid is None and max_uid is not None:
            updated_last_uid = int(max_uid)

        # --- Spam/Junk (Gmail + GMX + others): UNSEEN only ---
        spam_mails: list = []
        spam_box = _find_spam_mailbox_name(M)
        if spam_box:
            try:
                typ_sel, _ = M.select(spam_box)
                if typ_sel == "OK":
                    typ_s, data_s = M.uid("search", None, "UNSEEN")
                    if typ_s == "OK" and data_s and data_s[0]:
                        spam_uids = [int(x) for x in data_s[0].split() if x.isdigit()]
                        if spam_uids:
                            spam_mails = _fetch_uids(
                                sorted(spam_uids)[-DEFAULT_MAX_PER_ACCOUNT:],
                                uid_prefix="S:",
                            )
                            for su in spam_uids:
                                try:
                                    M.uid("store", str(su), "+FLAGS", r"(\\Seen)")
                                except Exception:
                                    pass
            except Exception:
                logger.exception("IMAP spam folder fetch failed box=%s", spam_box)
            finally:
                try:
                    M.select("INBOX")
                except Exception:
                    pass

        # --- Other folders (categories / custom): UNSEEN only ---
        extra_mails: list = []
        for i, box in enumerate(_list_extra_watch_mailboxes(M, spam_box=spam_box)):
            try:
                typ_sel, _ = M.select(box)
                if typ_sel != "OK":
                    continue
                typ_x, data_x = M.uid("search", None, "UNSEEN")
                if typ_x != "OK" or not data_x or not data_x[0]:
                    continue
                xuids = [int(x) for x in data_x[0].split() if x.isdigit()]
                if not xuids:
                    continue
                batch = _fetch_uids(
                    sorted(xuids)[-DEFAULT_MAX_PER_ACCOUNT:],
                    uid_prefix=f"X{i}:",
                )
                extra_mails.extend(batch)
                for xu in xuids:
                    try:
                        M.uid("store", str(xu), "+FLAGS", r"(\\Seen)")
                    except Exception:
                        pass
            except Exception:
                logger.exception("IMAP extra folder fetch failed box=%s", box)
            finally:
                try:
                    M.select("INBOX")
                except Exception:
                    pass

        mails = inbox_mails + spam_mails + extra_mails

        if last_uid is None:
            return mails, (int(max_uid) if max_uid is not None else last_uid)

        if not mails:
            return [], (int(max_uid) if max_uid is not None else last_uid)

        return mails, (int(max_uid) if max_uid is not None else last_uid)

    finally:
        try:
            if M is not None:
                M.logout()
        except Exception:
            pass


def _strip_html_to_text(text: str) -> str:
    if not text:
        return ""
    t = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    t = re.sub(r"</p\s*>", "\n", t, flags=re.I)
    t = re.sub(r"<[^>]+>", "", t)
    t = t.replace("&nbsp;", " ").replace("&quot;", '"').replace("&amp;", "&")
    return t


def _clean_mail_body_for_card(raw: str) -> str:
    """Текст письма для карточки: без HTML/CSS-мусора из шаблонов Google и т.п."""
    if not raw:
        return ""
    txt = raw
    low = txt.lower()
    if "<style" in low or "<html" in low or "<div" in low or "<span" in low:
        txt = re.sub(r"(?is)<style[^>]*>.*?</style>", "", txt)
        txt = _strip_html_to_text(txt)
    lines: list[str] = []
    for line in txt.replace("\r", "\n").split("\n"):
        s = line.strip()
        if not s:
            lines.append("")
            continue
        if re.match(r"^[\.\#\@\w\-\s,\[\]:]+\{", s):
            continue
        if re.match(r"^[\}\s;]+$", s):
            continue
        if s.startswith("@media") or s.startswith("@font-face"):
            continue
        lines.append(line.rstrip())
    txt = "\n".join(lines)
    txt = re.sub(r"\n{3,}", "\n\n", txt).strip()
    try:
        txt = html_module.unescape(txt)
    except Exception:
        pass
    return txt


_INCOMING_BODY_DEDUPE_MINUTES = 45


def _incoming_body_dedupe_key(body: str) -> str:
    """Один ответ продавца — Ricardo иногда шлёт 2 письма с разной темой и тем же текстом."""
    cleaned = _clean_mail_body_for_card((body or "").strip())
    norm = re.sub(r"\s+", " ", cleaned).strip().lower()
    if len(norm) < 16:
        return ""
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:40]


def _ensure_multiline_for_expandable(text: str) -> str:
    """Telegram показывает стрелку разворота только у многострочного expandable blockquote."""
    if not text:
        return "—"
    if "\n" in text:
        return text
    if len(text) <= 120:
        return text
    return "\n".join(text[i : i + 100] for i in range(0, len(text), 100))


def _extract_reply_only_preview(raw: str) -> str:
    """Preview for card.

    Требование из ТЗ (скрин №2):
    - показывать НЕ только последнее сообщение продавца,
      но и текст предыдущего письма (обычно это наше отправленное сообщение),
      если он присутствует в цепочке (quoted / 'Am ... schrieb', 'On ... wrote', etc.).
    - если в письме нет цепочки — показываем как раньше только ответ продавца.
    """
    if not raw:
        return ""

    txt = raw
    low = txt.lower()
    if "<html" in low or "<div" in low or "<span" in low or "<blockquote" in low:
        txt = _strip_html_to_text(txt)

    txt = txt.replace("\r\n", "\n").replace("\r", "\n")

    # 1) Верхняя часть: сообщение продавца (как раньше — до маркера цитирования)
    markers = [
        "\nOn ", "On ",
        "\nAm ", "Am ",
        "\nOp ", "Op ",
        "\nLe ", "Le ",
        "\n-----Original Message-----",
        "\nFrom:",
        "\nОт:",
    ]
    cut_pos = None
    for mk in markers:
        p = txt.find(mk)
        if p != -1:
            cut_pos = p if cut_pos is None else min(cut_pos, p)

    seller_part = txt if cut_pos is None else txt[:cut_pos]

    # отсекаем '>'-цитирование внутри seller_part
    seller_lines = []
    for line in seller_part.split("\n"):
        if line.strip().startswith(">") and seller_lines:
            break
        seller_lines.append(line)
    seller = "\n".join(seller_lines).strip()

    # 2) Попытка достать первую цитируемую часть (обычно наше письмо)
    quoted = ""
    if cut_pos is not None:
        rest = txt[cut_pos:]
        lines = rest.split("\n")
        start_idx = None
        for i, line in enumerate(lines):
            l = line.strip()
            if not l:
                continue
            if (
                (" schrieb" in l.lower())
                or (" wrote" in l.lower())
                or (" schreef" in l.lower())
                or (" a écrit" in l.lower())
                or ("original message" in l.lower())
            ):
                start_idx = i + 1
                break
            if l.startswith(">"):
                start_idx = i
                break

        if start_idx is None:
            start_idx = 0

        buf = []
        for j in range(start_idx, len(lines)):
            l = lines[j]
            ls = l.strip()
            if j != start_idx and (ls.lower().startswith("on ") or ls.lower().startswith("am ") or ls.lower().startswith("le ") or "-----original message-----" in ls.lower()):
                break
            if j != start_idx and ls.startswith("From:"):
                break
            if ls.startswith(">"):
                l = l.lstrip("> ")
                ls = l.strip()
            if not ls and buf:
                break
            buf.append(l)

        quoted = "\n".join(buf).strip()

    if quoted:
        return (seller or "").strip() + "\n\n" + "--------" + "\n" + (quoted or "").strip()

    return (seller or "").strip()


def _service_label_from_link(link: str) -> str:
    from services.offer_storage import marketplace_service_label_from_link

    return marketplace_service_label_from_link(link)


def _service_display_label(label: str | None) -> str:
    """Как FI WORKING: Facebook.com в карточке."""
    s = (label or "").strip()
    if not s:
        return ""
    low = s.lower()
    if low == "facebook.com":
        return "Facebook.com"
    return s


async def _find_duplicate_telegram_by_body(
    session,
    *,
    mail_db_id: int,
    user_id: int,
    account_id: int,
    from_email: str,
    body: str,
    cross_account: bool = True,
) -> int | None:
    from datetime import datetime, timedelta

    key = _incoming_body_dedupe_key(body)
    from_e = (from_email or "").strip().lower()
    if not key or not from_e:
        return None
    cutoff = datetime.utcnow() - timedelta(minutes=_INCOMING_BODY_DEDUPE_MINUTES)

    def _query(*, same_account_only: bool):
        q = (
            sa_select(IncomingMail.id, IncomingMail.body, IncomingMail.telegram_message_id)
            .where(IncomingMail.user_id == int(user_id))
            .where(func.lower(IncomingMail.from_email) == from_e)
            .where(IncomingMail.created_at >= cutoff)
            .where(IncomingMail.id != int(mail_db_id))
            .order_by(IncomingMail.id.desc())
            .limit(24)
        )
        if same_account_only:
            q = q.where(IncomingMail.account_id == int(account_id))
        return q

    for same_acc in (False, True) if cross_account else (True,):
        rows = (await session.execute(_query(same_account_only=same_acc))).all()
        for _rid, b, tid in rows:
            if tid is None or int(tid) <= 0:
                continue
            if _incoming_body_dedupe_key(b or "") == key:
                return int(tid)
    return None


async def _incoming_body_notify_inflight(
    session,
    *,
    mail_db_id: int,
    user_id: int,
    account_id: int,
    from_email: str,
    body: str,
) -> bool:
    from datetime import datetime, timedelta

    key = _incoming_body_dedupe_key(body)
    from_e = (from_email or "").strip().lower()
    if not key or not from_e:
        return False
    cutoff = datetime.utcnow() - timedelta(minutes=_INCOMING_BODY_DEDUPE_MINUTES)

    async def _rows(same_account_only: bool):
        q = (
            sa_select(IncomingMail.id, IncomingMail.body, IncomingMail.telegram_message_id)
            .where(IncomingMail.user_id == int(user_id))
            .where(func.lower(IncomingMail.from_email) == from_e)
            .where(IncomingMail.created_at >= cutoff)
            .where(IncomingMail.id != int(mail_db_id))
            .order_by(IncomingMail.id.desc())
            .limit(24)
        )
        if same_account_only:
            q = q.where(IncomingMail.account_id == int(account_id))
        return (await session.execute(q)).all()

    for same_acc in (False, True):
        for _rid, b, tid in await _rows(same_account_only=same_acc):
            if tid is None or int(tid) != -1:
                continue
            if _incoming_body_dedupe_key(b or "") == key:
                return True
    return False


async def _acquire_incoming_notify_lock(
    session,
    *,
    user_id: int,
    account_id: int,
    from_email: str,
    body: str,
) -> None:
    key = _incoming_body_dedupe_key(body)
    from_e = (from_email or "").strip().lower()
    if not key or not from_e:
        return
    lock_id = hash(f"{user_id}:{account_id}:{from_e}:{key}") & 0x7FFFFFFFFFFFFFFF
    try:
        from sqlalchemy import text

        bind = session.get_bind()
        if bind.dialect.name == "postgresql":
            got = (
                await session.execute(
                    text("SELECT pg_try_advisory_xact_lock(:k)"), {"k": lock_id}
                )
            ).scalar()
            if got is False:
                logger.debug("notify lock busy user=%s acc=%s", user_id, account_id)
    except Exception:
        pass


async def _find_duplicate_telegram_message_id(
    session,
    *,
    mail_db_id: int,
    user_id: int,
    account_id: int,
    from_email: str,
    subject: str,
    body: str,
) -> int | None:
    """Уже ушло в TG: тот же mail_id, или то же тело (Ricardo dual-mail / повторный poll).

    Не дедупим только по теме: в треде Re: одна и та же, а ответы разные
    («ja whahha» → пресет → «ja ofc sure») — каждый должен дать свою карточку.
    """
    del subject  # оставлен в сигнатуре для совместимости вызовов
    row = (
        await session.execute(
            sa_select(IncomingMail.telegram_message_id).where(
                IncomingMail.id == int(mail_db_id)
            )
        )
    ).scalar_one_or_none()
    if row is not None and int(row) > 0:
        return int(row)

    body_dup = await _find_duplicate_telegram_by_body(
        session,
        mail_db_id=int(mail_db_id),
        user_id=int(user_id),
        account_id=int(account_id),
        from_email=from_email,
        body=body,
    )
    if body_dup is not None:
        return int(body_dup)
    return None


async def _wait_duplicate_telegram_notify(
    session,
    *,
    mail_db_id: int,
    user_id: int,
    account_id: int,
    from_email: str,
    subject: str,
    body: str,
) -> int | None:
    """
    >0 — карточка уже в TG; None — можно отправлять; -1 — другой воркер шлёт, пропуск.
    """
    for _ in range(12):
        dup = await _find_duplicate_telegram_message_id(
            session,
            mail_db_id=int(mail_db_id),
            user_id=int(user_id),
            account_id=int(account_id),
            from_email=from_email,
            subject=subject,
            body=body,
        )
        if dup is not None and int(dup) > 0:
            return int(dup)
        if await _incoming_body_notify_inflight(
            session,
            mail_db_id=int(mail_db_id),
            user_id=int(user_id),
            account_id=int(account_id),
            from_email=from_email,
            body=body,
        ):
            await asyncio.sleep(0.35)
            continue
        return None
    return -1


async def _release_stale_telegram_notify_claims(
    session,
    *,
    older_than_minutes: int = 3,
) -> int:
    """Зависший claim (-1) после краша воркера — иначе IMAP навсегда молчит."""
    from datetime import datetime, timedelta

    cutoff = datetime.utcnow() - timedelta(minutes=max(1, int(older_than_minutes)))
    res = await session.execute(
        update(IncomingMail)
        .where(IncomingMail.telegram_message_id == -1)
        .where(IncomingMail.updated_at < cutoff)
        .values(telegram_message_id=None)
    )
    await session.commit()
    return int(res.rowcount or 0)


async def _try_claim_telegram_notify(session, mail_db_id: int) -> bool:
    """Один воркер на карточку (telegram_message_id=-1 — отправка в процессе)."""
    res = await session.execute(
        update(IncomingMail)
        .where(IncomingMail.id == int(mail_db_id))
        .where(IncomingMail.telegram_message_id.is_(None))
        .values(telegram_message_id=-1)
    )
    await session.commit()
    return bool(res.rowcount)


async def _release_telegram_notify_claim(session, mail_db_id: int) -> None:
    await session.execute(
        update(IncomingMail)
        .where(IncomingMail.id == int(mail_db_id))
        .where(IncomingMail.telegram_message_id == -1)
        .values(telegram_message_id=None)
    )
    await session.commit()


def _service_html(label: str) -> str:
    """Как «Товар» — моноширинный текст для копирования, без кликабельной ссылки и превью."""
    s = (label or "").strip()
    if not s:
        return ""
    return f"<code>{_e(s)}</code>"


def render_mail_text_chunks(
    *,
    account_email: str,
    inbox_label: str | None = None,
    from_name: str,
    from_email: str,
    subject: str,
    body: str,
    offer_id: int | None = None,
    link_id: str | None = None,
    service_label: str | None = None,
    product_title: str | None = None,
    offer_price: str | None = None,
    translation: str | None = None,
) -> list[str]:
    shown = _ensure_multiline_for_expandable(_clean_mail_body_for_card((body or "").strip()))

    extra = ""
    lid = (link_id or "").strip()
    if lid and offer_id:
        extra += f"<b>ID:</b> <code>{_e(lid)}</code>\n"
    if offer_id:
        extra += f"<b>Лот:</b> <code>{int(offer_id)}</code>\n"
    if service_label:
        extra += f"<b>Сервис:</b> {_service_html(_service_display_label(service_label))}\n"
    if product_title:
        extra += f"<b>Товар:</b> <code>{_e(product_title)}</code>\n"
    price_s = (offer_price or "").strip()
    if price_s:
        extra += f"<b>Цена:</b> <code>{_e(price_s)}</code>\n"
    if extra:
        extra = "\n" + extra

    burst = html_emoji("burst")
    label = (inbox_label or "").strip()
    if label:
        label_line = f'{burst} Получено сообщение на "<b>{_e(label)}</b>"'
    else:
        label_line = f"{burst} Получено сообщение на <code>{_e(account_email)}</code>"

    from_disp = (from_name or "").strip() or from_email
    head = (
        f"{label_line}\n"
        f"<code>{_e(account_email)}</code>\n"
        f'от "<b>{_e(from_disp)}</b>" <code>{_e(from_email)}</code>\n'
        f"{extra}\n"
        f"<b>Тема:</b>\n<blockquote><code>{_e(subject or '—')}</code></blockquote>\n\n"
        f"<b>Текст:</b>\n"
    )

    body_limit = 1400 if translation else 3200
    body_text = _e((shown[:body_limit] if shown else "—"))
    msg = head + f"<blockquote expandable><code>{body_text}</code></blockquote>"
    if translation:
        tr = _ensure_multiline_for_expandable(str(translation)[:1400])
        msg += (
            "\n\n<b>Перевод:</b>\n"
            f"<blockquote expandable><code>{_e(tr)}</code></blockquote>"
        )
    return [msg]


def format_first_incoming_photo_caption(
    *,
    product_title: str | None,
    offer_price: str | None,
) -> str:
    """Reply-фото к первому письму продавца (как в старых ботах)."""
    lines: list[str] = []
    title = (product_title or "").strip()
    if title:
        lines.append(f"{html_emoji('pin')} <b>{_e(title)}</b>")
    lines.append(f"{html_emoji('camera')} Фото товара")
    price_s = (offer_price or "").strip()
    if price_s:
        lines.append(f"{html_emoji('price')} <b>Цена:</b> {_e(price_s)} {html_emoji('price')}")
    return "\n".join(lines)


def build_kb(
    acc_id: int,
    uid: str,
    *,
    mail_id: int | None = None,
) -> InlineKeyboardMarkup:
    translate_cb = f"mail_translate:{mail_id}" if mail_id else f"mail_translate_stub:{acc_id}:{uid}"
    link_cb = f"goo_mail:{mail_id}" if mail_id else f"goo_link:{acc_id}:{uid}"
    rows: List[List[InlineKeyboardButton]] = [
        [inline_button("compass", "Перевести", callback_data=translate_cb)],
        [inline_button("puzzle", "Создать ссылку", callback_data=link_cb)],
        [
            inline_button(
                "write",
                "Написать ещё",
                callback_data=(
                    f"mail_reply_db:{int(mail_id)}"
                    if mail_id
                    else f"mail_reply:{acc_id}:{uid}"
                ),
            )
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _find_offer_if_unique_email(
    session,
    *,
    user_id: int,
    from_email: str,
) -> Offer | None:
    """Только если у продавца ровно одно объявление с этим email."""
    canon = _canon_email(from_email)
    if not canon:
        return None
    ids = (
        await session.execute(
            sa_select(Offer.id)
            .join(OfferEmail, OfferEmail.offer_id == Offer.id)
            .where(Offer.user_id == int(user_id))
            .where(func.lower(OfferEmail.email) == canon)
        )
    ).scalars().all()
    uniq = {int(x) for x in ids if x}
    if len(uniq) != 1:
        return None
    oid = next(iter(uniq))
    return (
        await session.execute(
            sa_select(Offer).where(Offer.id == int(oid)).where(Offer.user_id == int(user_id)).limit(1)
        )
    ).scalars().first()


async def resolve_offer_for_mail_card(
    session,
    *,
    user_id: int,
    from_email: str,
    resolved_offer_id: int | None = None,
    ad_url: str | None = None,
    inbox_email: str | None = None,
    subject: str = "",
    from_name: str = "",
    body_text: str = "",
    mailing_bound: bool = False,
) -> Offer | None:
    from services.incoming_lead_resolve import resolve_offer_for_incoming_lead
    from services.offer_storage import normalize_incoming_seller_email

    contact = normalize_incoming_seller_email(from_email) or (from_email or "").strip().lower()
    off, _url, _how, _snap = await resolve_offer_for_incoming_lead(
        session,
        user_id=int(user_id),
        contact_email=contact,
        subject=subject,
        from_name=from_name,
        body_text=body_text,
        resolved_offer_id=resolved_offer_id,
        mail_ad_url=ad_url,
        inbox_email=inbox_email,
        mailing_bound=mailing_bound,
    )
    return off


async def mail_card_offer_meta(
    session,
    *,
    user_id: int,
    from_email: str,
    resolved_offer_id: int | None = None,
    ad_url: str | None = None,
    inbox_email: str | None = None,
    subject: str = "",
    from_name: str = "",
    body_text: str = "",
    stored_product_title: str | None = None,
    stored_offer_price: str | None = None,
    stored_photo_url: str | None = None,
    stored_service_label: str | None = None,
    stored_outgoing_subject: str | None = None,
    mailing_bound: bool = False,
) -> tuple[int | None, str | None, str | None, str | None, str | None, str | None]:
    from services.incoming_lead_resolve import resolve_offer_for_incoming_lead
    from services.offer_storage import normalize_incoming_seller_email

    if (stored_product_title or "").strip() and resolved_offer_id:
        from services.offer_storage import live_user_offer

        live = await live_user_offer(
            session, user_id=int(user_id), offer_id=int(resolved_offer_id)
        )
        if live:
            return (
                int(live.id),
                (stored_service_label or "").strip() or None,
                (stored_product_title or "").strip() or None,
                (stored_photo_url or "").strip() or None,
                (stored_offer_price or "").strip() or None,
                (stored_outgoing_subject or "").strip() or None,
            )

    contact = normalize_incoming_seller_email(from_email) or (from_email or "").strip().lower()
    off, _url, _how, snap = await resolve_offer_for_incoming_lead(
        session,
        user_id=int(user_id),
        contact_email=contact,
        subject=subject or "",
        from_name=from_name,
        body_text=body_text or "",
        resolved_offer_id=resolved_offer_id,
        mail_ad_url=ad_url,
        inbox_email=inbox_email,
        mailing_bound=mailing_bound,
    )
    if not off:
        return None, None, None, None, None, None
    return (
        int(off.id),
        (snap.get("service_label") or "").strip() or None,
        (snap.get("product_title") or "").strip() or None,
        (snap.get("photo_url") or "").strip() or None,
        (snap.get("offer_price") or "").strip() or None,
        (snap.get("outgoing_mail_subject") or "").strip() or None,
    )


async def is_first_inbound_mail_for_seller(
    session,
    *,
    user_id: int,
    account_id: int,
    from_email: str,
    mail_id: int,
) -> bool:
    """
    Первое входящее от этого продавца на ящик, уже ушедшее в TG.
    Лот / товар / цена / фото — только на этой карточке; повторные письма — короткие reply.
    """
    if not int(mail_id or 0):
        return False
    fe = _canon_email(from_email)
    if not fe:
        return False
    prior = (
        await session.execute(
            sa_select(func.count(IncomingMail.id))
            .where(IncomingMail.user_id == int(user_id))
            .where(IncomingMail.account_id == int(account_id))
            .where(func.lower(IncomingMail.from_email) == fe)
            .where(IncomingMail.id < int(mail_id))
            .where(IncomingMail.telegram_message_id.isnot(None))
            .where(IncomingMail.telegram_message_id > 0)
        )
    ).scalar() or 0
    return int(prior) == 0


async def is_first_inbound_mail_for_seller_offer(
    session,
    *,
    user_id: int,
    account_id: int,
    from_email: str,
    resolved_offer_id: int,
    mail_id: int,
) -> bool:
    """Совместимость: «первое» = первое от продавца на ящик (лот больше не режет)."""
    _ = resolved_offer_id
    return await is_first_inbound_mail_for_seller(
        session,
        user_id=user_id,
        account_id=account_id,
        from_email=from_email,
        mail_id=mail_id,
    )


async def seller_thread_tg_anchor_message_id(
    session,
    *,
    user_id: int,
    account_id: int,
    from_email: str,
    conv: ConversationLink | None = None,
) -> int | None:
    """Якорь reply: ConversationLink или самое раннее TG-сообщение от этого продавца."""
    try:
        if conv and getattr(conv, "tg_message_id", None):
            tid = int(conv.tg_message_id)
            if tid > 0:
                return tid
    except Exception:
        pass
    fe = _canon_email(from_email)
    if not fe:
        return None
    tid = (
        await session.execute(
            sa_select(IncomingMail.telegram_message_id)
            .where(IncomingMail.user_id == int(user_id))
            .where(IncomingMail.account_id == int(account_id))
            .where(func.lower(IncomingMail.from_email) == fe)
            .where(IncomingMail.telegram_message_id.isnot(None))
            .where(IncomingMail.telegram_message_id > 0)
            .order_by(IncomingMail.id.asc())
            .limit(1)
        )
    ).scalar_one_or_none()
    try:
        return int(tid) if tid and int(tid) > 0 else None
    except Exception:
        return None


async def seller_offer_photo_sent_recently(
    session,
    *,
    user_id: int,
    account_id: int,
    from_email: str,
    resolved_offer_id: int,
    mail_id: int,
) -> bool:
    """Не слать второе фото, если от этого продавца на ящик уже уходило TG-фото недавно."""
    from datetime import datetime, timedelta

    _ = resolved_offer_id
    if not int(mail_id or 0):
        return False
    fe = _canon_email(from_email)
    if not fe:
        return False
    cutoff = datetime.utcnow() - timedelta(minutes=_INCOMING_BODY_DEDUPE_MINUTES)
    prior = (
        await session.execute(
            sa_select(func.count(IncomingMail.id))
            .where(IncomingMail.user_id == int(user_id))
            .where(IncomingMail.account_id == int(account_id))
            .where(func.lower(IncomingMail.from_email) == fe)
            .where(IncomingMail.telegram_message_id.isnot(None))
            .where(IncomingMail.telegram_message_id > 0)
            .where(IncomingMail.id != int(mail_id))
            .where(IncomingMail.created_at >= cutoff)
            .where(IncomingMail.photo_url.isnot(None))
            .where(IncomingMail.photo_url != "")
        )
    ).scalar() or 0
    return int(prior) > 0


async def repair_unbound_inbound_telegram_card(
    bot: Bot,
    *,
    chat_id: int,
    mail_id: int,
    inbox_label: str | None = None,
) -> bool:
    """
    Письмо уже ушло в TG без лота (старый деплой / резолв без inbox_email) — пересобрать карточку.
    """
    try:
        async with _imap_db_session() as session:
            mail = (
                await session.execute(
                    sa_select(IncomingMail).where(IncomingMail.id == int(mail_id)).limit(1)
                )
            ).scalars().first()
            if not mail:
                return False
            if getattr(mail, "resolved_offer_id", None):
                return False
            tid = getattr(mail, "telegram_message_id", None)
            if not tid or int(tid) <= 0:
                return False

            from services.incoming_lead_resolve import resolve_offer_for_incoming_lead
            from services.offer_storage import normalize_incoming_seller_email

            contact = normalize_incoming_seller_email(getattr(mail, "from_email", "") or "") or (
                getattr(mail, "from_email", "") or ""
            ).strip()
            off, listing_url, _how, snap = await resolve_offer_for_incoming_lead(
                session,
                user_id=int(mail.user_id),
                contact_email=contact,
                subject=(getattr(mail, "subject", "") or "").strip(),
                from_name=(getattr(mail, "from_name", "") or "").strip(),
                body_text=(getattr(mail, "body", "") or "").strip(),
                inbox_email=(getattr(mail, "account_email", "") or "").strip() or None,
                resolved_offer_id=None,
            )
            if off:
                mail.resolved_offer_id = int(off.id)
                mail.mailing_bound = True
                if (listing_url or "").strip():
                    mail.ad_url = listing_url.strip()
                pt = (snap.get("product_title") or "").strip()
                if pt:
                    mail.product_title = pt[:500]
                pr = (snap.get("offer_price") or "").strip()
                if pr:
                    mail.offer_price = pr[:64]
                ph = (snap.get("photo_url") or "").strip()
                if ph:
                    mail.photo_url = ph[:2000]
                sl = (snap.get("service_label") or "").strip()
                if sl:
                    mail.service_label = sl[:64]
                await session.flush()

            text, kb = await build_mail_card_from_mail(
                session, mail, inbox_label=inbox_label
            )
            oid = getattr(mail, "resolved_offer_id", None)
            photo_url = (getattr(mail, "photo_url", None) or "").strip()
            product_title = (getattr(mail, "product_title", None) or "").strip() or None
            offer_price = (getattr(mail, "offer_price", None) or "").strip() or None
            await _db_commit_retry(session)

        if not oid:
            return False

        await bot.edit_message_text(
            chat_id=int(chat_id),
            message_id=int(tid),
            text=text,
            reply_markup=kb,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
        photo_url = (getattr(mail, "photo_url", None) or "").strip()
        if photo_url:
            cap = format_first_incoming_photo_caption(
                product_title=product_title,
                offer_price=offer_price,
            )
            try:
                await bot.send_photo(
                    chat_id=int(chat_id),
                    photo=photo_url,
                    caption=cap,
                    parse_mode="HTML",
                    reply_to_message_id=int(tid),
                )
            except Exception:
                logger.exception("repair inbound photo mail_id=%s", mail_id)
        return True
    except Exception:
        logger.exception("repair_unbound_inbound_telegram_card mail_id=%s", mail_id)
        return False


async def build_mail_card_from_mail(
    session,
    mail: IncomingMail,
    *,
    inbox_label: str | None = None,
    translation: str | None = None,
) -> tuple[str, InlineKeyboardMarkup]:
    if inbox_label is None:
        try:
            u = (
                await session.execute(sa_select(User).where(User.id == int(mail.user_id)).limit(1))
            ).scalars().first()
            if u:
                inbox_label = (getattr(u, "sender_name", None) or "").strip() or None
        except Exception:
            inbox_label = None

    body_full = (getattr(mail, "body", None) or "").strip()
    buyer_label = inbox_label
    oid, service_label, product_title, photo_url, offer_price, _out_subj = await mail_card_offer_meta(
        session,
        user_id=int(mail.user_id),
        from_email=str(getattr(mail, "from_email", "") or ""),
        resolved_offer_id=getattr(mail, "resolved_offer_id", None),
        ad_url=(getattr(mail, "ad_url", "") or "").strip() or None,
        inbox_email=str(getattr(mail, "account_email", "") or ""),
        subject=str(getattr(mail, "subject", "") or ""),
        from_name=str(getattr(mail, "from_name", "") or ""),
        body_text=body_full,
        stored_product_title=(getattr(mail, "product_title", None) or "").strip() or None,
        stored_offer_price=(getattr(mail, "offer_price", None) or "").strip() or None,
        stored_photo_url=(getattr(mail, "photo_url", None) or "").strip() or None,
        stored_service_label=(getattr(mail, "service_label", None) or "").strip() or None,
        stored_outgoing_subject=(getattr(mail, "outgoing_mail_subject", None) or "").strip() or None,
        mailing_bound=bool(getattr(mail, "mailing_bound", False)),
    )
    off_for_label = None
    if oid:
        off_for_label = (
            await session.execute(
                sa_select(Offer).where(Offer.id == int(oid)).where(Offer.user_id == int(mail.user_id)).limit(1)
            )
        ).scalars().first()
    if off_for_label:
        from services.incoming_validated_offer import inbound_card_inbox_label

        inbox_label = inbound_card_inbox_label(
            off_for_label, buyer_display_name=(buyer_label or "")
        ) or inbox_label

    generated_link = (getattr(mail, "generated_link", None) or "").strip()
    conv = await _load_convlink(
        user_id=int(mail.user_id),
        inbox_email=str(getattr(mail, "account_email", "") or ""),
        contact_email=str(getattr(mail, "from_email", "") or ""),
    )
    if conv and (conv.generated_link or "").strip():
        generated_link = (conv.generated_link or "").strip()
    link_id = link_id_from_generated_url(generated_link)

    card_subject = str(getattr(mail, "subject", "") or "").strip()
    is_first_card = True
    try:
        is_first_card = await is_first_inbound_mail_for_seller(
            session,
            user_id=int(mail.user_id),
            account_id=int(getattr(mail, "account_id", 0) or 0),
            from_email=str(getattr(mail, "from_email", "") or ""),
            mail_id=int(mail.id),
        )
    except Exception:
        is_first_card = True
    show_oid = oid if is_first_card else None
    show_service = service_label if is_first_card else None
    show_product = (product_title or None) if is_first_card else None
    show_price = offer_price if is_first_card else None
    chunks = render_mail_text_chunks(
        account_email=str(getattr(mail, "account_email", "") or ""),
        inbox_label=inbox_label,
        from_name=str(getattr(mail, "from_name", "") or ""),
        from_email=str(getattr(mail, "from_email", "") or ""),
        subject=card_subject,
        body=body_full,
        offer_id=show_oid,
        link_id=link_id,
        service_label=show_service,
        product_title=show_product,
        offer_price=show_price,
        translation=translation,
    )
    text = (chunks[0] if chunks else "—")[:4096]
    kb = build_kb(
        int(getattr(mail, "account_id", 0) or 0),
        str(getattr(mail, "imap_uid", 0) or "0"),
        mail_id=int(mail.id),
    )
    return text, kb


def _resolve_generated_link_for_card(
    *,
    conv: ConversationLink | None,
    mail_generated_link: str | None = None,
    meta_generated_link: str | None = None,
) -> str:
    for candidate in (
        meta_generated_link,
        mail_generated_link,
        (conv.generated_link if conv else None),
    ):
        s = (candidate or "").strip()
        if s:
            return s
    return ""


async def _try_pin(bot: Bot, chat_id: int, message_id: int) -> None:
    try:
        await bot.pin_chat_message(chat_id=chat_id, message_id=message_id, disable_notification=True)
    except Exception:
        pass


async def _process_mails_for_account(
    bot: Bot,
    *,
    acc_id: int,
    tg_id: int,
    user_id: int,
    account_email: str,
    mails: List[Tuple[str, str, str, str, str, str, str]],
    max_per_account: int,
    last_uid: Optional[int],
) -> int:
    return await _process_mails_for_account_impl(
        bot,
        acc_id=acc_id,
        tg_id=tg_id,
        user_id=user_id,
        account_email=account_email,
        mails=mails,
        max_per_account=max_per_account,
        last_uid=last_uid,
    )


async def _process_mails_for_account_impl(
    bot: Bot,
    *,
    acc_id: int,
    tg_id: int,
    user_id: int,
    account_email: str,
    mails: List[Tuple[str, str, str, str, str, str, str]],
    max_per_account: int,
    last_uid: Optional[int],
) -> int:
    forwarded = 0

    inbox_label: str | None = None
    try:
        async with _imap_db_session() as _s0:
            u0 = (
                await _s0.execute(sa_select(User).where(User.id == int(user_id)).limit(1))
            ).scalars().first()
            if u0:
                inbox_label = (getattr(u0, "sender_name", None) or "").strip() or None
    except Exception:
        inbox_label = None

    if last_uid is not None:
        LAST_UID[acc_id] = int(last_uid)
        await _set_last_seen_uid(acc_id, int(last_uid))

    for row in (mails or [])[:max_per_account]:
        # Backward-compatible: 6/7/9-tuples
        rfc_in_reply_to = ""
        rfc_references = ""
        if len(row) >= 9:
            (
                uid,
                from_email,
                from_name,
                subject,
                date_str,
                body,
                rfc_message_id,
                rfc_in_reply_to,
                rfc_references,
            ) = row[:9]
        elif len(row) >= 7:
            uid, from_email, from_name, subject, date_str, body, rfc_message_id = row[:7]
        else:
            uid, from_email, from_name, subject, date_str, body = row[:6]
            rfc_message_id = ""
        uid_key = uid
        is_spam_box = False
        is_extra_box = False
        uid_num = None
        if isinstance(uid, str) and uid.startswith("S:"):
            is_spam_box = True
            try:
                uid_num = int(uid.split(":", 1)[1])
            except Exception:
                continue
        elif isinstance(uid, str) and re.match(r"^X\d+:", uid):
            is_extra_box = True
            try:
                uid_num = int(uid.rsplit(":", 1)[1])
            except Exception:
                continue
        else:
            try:
                uid_num = int(uid)
            except Exception:
                continue

        # Только явный Gmail block / 5.7.1 — не любой DSN об недоставке получателю.
        smtp_block_bounce = _is_smtp_block_bounce(from_email, subject, body)
        from_email_clean_pre = (from_email or "").strip().lower()
        recipient_dsn_bounce = (
            not smtp_block_bounce
            and _is_mailer_daemon_notice(from_email_clean_pre, subject or "")
            and _is_recipient_delivery_failure_bounce(subject or "", body or "")
        )
        mailer_daemon = _is_mailer_daemon_notice(from_email_clean_pre, subject or "")

        # Whitelist: в бот/БД только продавцы с рассылкой у этого user.
        # Bounce/mailer-daemon пропускаем (блок SMTP / недоставка).
        if not smtp_block_bounce and not mailer_daemon:
            try:
                async with _imap_db_session() as _s:
                    ok_mailed = await is_inbound_from_mailed_seller(
                        _s, int(user_id), str(from_email or "")
                    )
                if not ok_mailed:
                    continue
            except Exception:
                logger.exception("mailed-seller allow-check failed acc=%s", acc_id)
                # Не глотаем ответ продавца из‑за сбоя БД.

        if (not is_spam_box) and (not is_extra_box) and _looks_like_spam(
            from_email, from_name, subject, body
        ):
            continue

        if (not is_spam_box) and (not is_extra_box) and _is_automated_system_sender(
            from_email_clean_pre, from_name or "", subject or ""
        ):
            continue

        try:
            body_clean = (body or "").strip()
            from_email_clean = (from_email or "").strip().lower()
            skip_telegram_notify = _is_google_system_mail(
                from_email_clean, from_name or "", subject or ""
            )
            if smtp_block_bounce:
                skip_telegram_notify = True
            elif recipient_dsn_bounce:
                skip_telegram_notify = True
            elif _is_mailer_daemon_notice(from_email_clean, subject or ""):
                skip_telegram_notify = False
            inbox_email_clean = (account_email or "").strip().lower()
            rfc_mid_clean = (rfc_message_id or "").strip()
            rfc_irt_clean = (rfc_in_reply_to or "").strip()
            rfc_refs_clean = (rfc_references or "").strip()

            FULL_BODIES[(acc_id, uid_key)] = body_clean
            FULL_META[(acc_id, uid_key)] = {
                "from_email": from_email_clean,
                "from_name": (from_name or "").strip(),
                "subject": subject or "",
                "account_email": inbox_email_clean,
                "date_str": date_str or "",
                "rfc_message_id": rfc_mid_clean,
                "rfc_in_reply_to": rfc_irt_clean,
                "rfc_references": rfc_refs_clean,
            }

            resolved_offer_id: int | None = None
            resolved_offer_email_id: int | None = None
            mail_db_id: int | None = None
            account_already_smtp_blocked = False
            saved_outgoing_mail_subject = ""
            mailing_bound_flag = False
            saved_product_title = ""
            saved_offer_price = ""
            saved_photo_url = ""
            saved_service_label = ""
            bound_offer: Offer | None = None
            ad_url: str | None = None
            try:
                async with _imap_db_session() as session:

                    if smtp_block_bounce:
                        acc_st = (
                            await session.execute(
                                sa_select(EmailAccount.status).where(
                                    EmailAccount.id == int(acc_id)
                                ).limit(1)
                            )
                        ).scalar_one_or_none()
                        account_already_smtp_blocked = (
                            str(acc_st or "").strip().lower() == "smtp_blocked"
                        )

                    existing = (
                        await session.execute(
                            sa_select(IncomingMail)
                            .where(IncomingMail.account_id == int(acc_id))
                            .where(IncomingMail.imap_uid == int(uid_num))
                            .limit(1)
                        )
                    ).scalars().first()
                    already_notified_tg = None
                    if existing and getattr(existing, "telegram_message_id", None) is not None:
                        tid0 = int(existing.telegram_message_id)
                        if tid0 > 0:
                            already_notified_tg = tid0
                        elif tid0 == -1:
                            await _release_telegram_notify_claim(session, int(existing.id))
                            existing.telegram_message_id = None

                    if not existing:
                        existing = IncomingMail(
                            user_id=int(user_id),
                            account_id=int(acc_id),
                            imap_uid=int(uid_num),
                        )
                        session.add(existing)

                    # Сначала базовые поля в БД — кнопки «Ссылка»/«Перевести» не должны падать,
                    # даже если подбор оффера ниже упадёт.
                    existing.account_email = inbox_email_clean
                    existing.from_email = from_email_clean
                    existing.from_name = (from_name or "").strip() or None
                    existing.subject = (subject or "").strip() or None
                    existing.date_str = (date_str or "").strip() or None
                    existing.body = body_clean or None
                    if rfc_mid_clean:
                        existing.rfc_message_id = rfc_mid_clean[:512]
                    if rfc_irt_clean:
                        existing.rfc_in_reply_to = rfc_irt_clean[:512]
                    if rfc_refs_clean:
                        existing.rfc_references = rfc_refs_clean[:4000]
                    await session.flush()
                    mail_db_id = int(existing.id)

                    try:
                        from services.incoming_lead_resolve import resolve_offer_for_incoming_lead
                        from services.offer_storage import normalize_incoming_seller_email

                        if not smtp_block_bounce and not mailer_daemon:
                            contact = (
                            normalize_incoming_seller_email(from_email_clean)
                            or from_email_clean
                        )
                            off_b, listing_url, _how_b, lead_snap = (
                                await resolve_offer_for_incoming_lead(
                                    session,
                                    user_id=int(user_id),
                                    contact_email=contact,
                                    subject=subject or "",
                                    from_name=(from_name or "").strip(),
                                    body_text=body_clean or "",
                                    resolved_offer_id=getattr(
                                        existing, "resolved_offer_id", None
                                    ),
                                    mail_ad_url=(getattr(existing, "ad_url", "") or "").strip()
                                    or None,
                                    inbox_email=inbox_email_clean,
                                )
                            )
                            if off_b and _how_b:
                                logger.info(
                                    "inbound bind mail_id=%s from=%s how=%s offer_id=%s",
                                    mail_db_id,
                                    contact,
                                    _how_b,
                                    int(off_b.id),
                                )
                            if off_b:
                                bound_offer = off_b
                                resolved_offer_id = int(off_b.id)
                                mailing_bound_flag = True
                                existing.resolved_offer_id = resolved_offer_id
                                existing.mailing_bound = True
                                if (listing_url or "").strip():
                                    existing.ad_url = listing_url.strip()
                                    ad_url = listing_url.strip()
                                saved_product_title = (
                                    lead_snap.get("product_title") or ""
                                ).strip()
                                saved_offer_price = (lead_snap.get("offer_price") or "").strip()
                                saved_photo_url = (lead_snap.get("photo_url") or "").strip()
                                saved_service_label = (
                                    lead_snap.get("service_label") or ""
                                ).strip()
                                if saved_product_title:
                                    existing.product_title = saved_product_title[:500]
                                if saved_offer_price:
                                    from services.html_reply import _format_html_price

                                    incoming_ok = bool(_format_html_price(saved_offer_price))
                                    if incoming_ok or not (existing.offer_price or "").strip():
                                        existing.offer_price = saved_offer_price[:64]
                                if saved_photo_url:
                                    existing.photo_url = saved_photo_url[:2000]
                                if saved_service_label:
                                    existing.service_label = saved_service_label[:64]
                    except Exception:
                        logger.exception(
                            "Validated offer bind IncomingMail id=%s acc=%s uid=%s",
                            mail_db_id,
                            acc_id,
                            uid_num,
                        )
                    try:
                        if mailer_daemon or smtp_block_bounce:
                            conv_pin = None
                        else:
                            conv_pin = (
                            await session.execute(
                                sa_select(ConversationLink).where(
                                    ConversationLink.user_id == int(user_id),
                                    func.lower(ConversationLink.account_email)
                                    == inbox_email_clean.lower(),
                                    func.lower(ConversationLink.from_email)
                                    == from_email_clean.lower(),
                                )
                            )
                        ).scalars().first()
                        if conv_pin:
                            pin_link = (getattr(conv_pin, "generated_link", None) or "").strip()
                            pin_price = (
                                getattr(conv_pin, "last_generated_price", None) or ""
                            ).strip()
                            if pin_link:
                                existing.generated_link = pin_link
                            if pin_price:
                                existing.offer_price = pin_price[:64]
                    except Exception:
                        logger.exception(
                            "Failed pin last generated link acc=%s uid=%s", acc_id, uid_num
                        )

                    if not smtp_block_bounce and not mailer_daemon:
                        try:
                            from models import MailingSendLog
                            from services.email_threading import absorb_inbound_thread_hints

                            mailed_rcpt = None
                            if resolved_offer_id:
                                mailed_rcpt = (
                                    await session.execute(
                                        sa_select(MailingSendLog.recipient_email)
                                        .where(MailingSendLog.user_id == int(user_id))
                                        .where(MailingSendLog.offer_id == int(resolved_offer_id))
                                        .order_by(
                                            MailingSendLog.sent_at.desc(),
                                            MailingSendLog.id.desc(),
                                        )
                                        .limit(1)
                                    )
                                ).scalar_one_or_none()
                            await absorb_inbound_thread_hints(
                                session,
                                user_id=int(user_id),
                                inbox_email=inbox_email_clean,
                                contact_email=from_email_clean,
                                inbound_message_id=rfc_mid_clean or None,
                                in_reply_to=rfc_irt_clean or None,
                                references=rfc_refs_clean or None,
                                mailing_recipient=(str(mailed_rcpt).strip() if mailed_rcpt else None),
                            )
                        except Exception:
                            logger.exception(
                                "absorb inbound thread hints failed mail_id=%s",
                                mail_db_id,
                            )

                    await _db_commit_retry(session)

            except Exception:
                logger.exception("Failed to persist IncomingMail acc=%s uid=%s", acc_id, uid)

            if recipient_dsn_bounce:
                try:
                    from services.bounce_recipient import purge_from_dsn_body

                    async with _imap_db_session() as session:
                        removed, bounced_addr = await purge_from_dsn_body(
                            session,
                            user_id=int(user_id),
                            subject=subject or "",
                            body=body_clean or "",
                        )
                    if removed and bounced_addr:
                        logger.info(
                            "recipient DSN: removed %s queue rows for %s user=%s",
                            removed,
                            bounced_addr,
                            user_id,
                        )
                except Exception:
                    logger.exception("Failed to purge bounced recipient user=%s", user_id)
                forwarded += 1
                continue

            # Message blocked: не слать карточки (Перевести / ссылка бессмысленны).
            # Первый раз — SMTP off + короткая строка; повторы — тихо.
            if smtp_block_bounce:
                if not account_already_smtp_blocked:
                    try:
                        async with _imap_db_session() as session:
                            acc_pre = (
                                await session.execute(
                                    sa_select(EmailAccount)
                                    .where(EmailAccount.id == int(acc_id))
                                    .limit(1)
                                )
                            ).scalars().first()
                            if acc_pre:
                                from services.smtp_block_control import mark_account_smtp_blocked

                                await mark_account_smtp_blocked(
                                    session,
                                    acc_pre,
                                    (body_clean or subject or "SMTP block bounce")[:1000],
                                    db_user_id=int(user_id),
                                    bot=bot,
                                    chat_id=int(tg_id),
                                    force=True,
                                )
                    except Exception:
                        logger.exception("Failed mark smtp_blocked acc=%s", acc_id)
                forwarded += 1
                continue

            if skip_telegram_notify:
                forwarded += 1
                continue

            if already_notified_tg:
                if not resolved_offer_id and mail_db_id:
                    await repair_unbound_inbound_telegram_card(
                        bot,
                        chat_id=int(tg_id),
                        mail_id=int(mail_db_id),
                        inbox_label=inbox_label,
                    )
                forwarded += 1
                continue

            await _upsert_convlink(
                user_id=user_id,
                inbox_email=_canon_email(inbox_email_clean),
                contact_email=_canon_email(from_email_clean),
                ad_url=ad_url,
                pinned_offer_id=int(resolved_offer_id) if resolved_offer_id else None,
                pinned_outgoing_subject=None,
            )

            conv = await _load_convlink(
                user_id=user_id,
                inbox_email=_canon_email(inbox_email_clean),
                contact_email=_canon_email(from_email_clean),
            )

            offer_id = int(resolved_offer_id) if resolved_offer_id else None
            product_title = (saved_product_title or "").strip() or None
            offer_price = (saved_offer_price or "").strip() or None
            photo_url = (saved_photo_url or "").strip() or None
            service_label = (saved_service_label or "").strip() or None

            card_inbox_label = inbox_label
            if bound_offer:
                from services.incoming_validated_offer import inbound_card_inbox_label

                card_inbox_label = (
                    inbound_card_inbox_label(
                        bound_offer, buyer_display_name=(inbox_label or "")
                    )
                    or inbox_label
                )

            # Тема = реальный subject письма, не название товара.
            card_subject = (subject or "").strip()
            link_id = None
            if conv and (conv.generated_link or "").strip():
                link_id = link_id_from_generated_url((conv.generated_link or "").strip())

            # Лот/товар/цена/фото — только на первом входящем от продавца, не на DSN.
            is_first_card = True
            photo_to_send: str | None = None
            photo_caption: str | None = None
            if mailer_daemon or smtp_block_bounce:
                is_first_card = False
            elif mail_db_id:
                try:
                    async with _imap_db_session() as _s2:
                        is_first_card = await is_first_inbound_mail_for_seller(
                            _s2,
                            user_id=int(user_id),
                            account_id=int(acc_id),
                            from_email=str(from_email_clean).strip(),
                            mail_id=int(mail_db_id),
                        )
                        if is_first_card and photo_url:
                            dup_photo = False
                            if offer_id:
                                dup_photo = await seller_offer_photo_sent_recently(
                                    _s2,
                                    user_id=int(user_id),
                                    account_id=int(acc_id),
                                    from_email=str(from_email_clean).strip(),
                                    resolved_offer_id=int(offer_id),
                                    mail_id=int(mail_db_id),
                                )
                            if not dup_photo:
                                photo_to_send = photo_url
                                photo_caption = format_first_incoming_photo_caption(
                                    product_title=product_title,
                                    offer_price=offer_price,
                                )
                except Exception:
                    logger.exception(
                        "first-incoming card check from=%s mail_id=%s",
                        from_email_clean,
                        mail_db_id,
                    )

            show_offer_id = offer_id if is_first_card else None
            show_service = service_label if is_first_card else None
            show_product = product_title if is_first_card else None
            show_price = offer_price if is_first_card else None

            chunks = render_mail_text_chunks(
                account_email=account_email,
                inbox_label=card_inbox_label,
                from_name=from_name,
                from_email=from_email,
                subject=card_subject,
                body=body,
                offer_id=show_offer_id,
                link_id=link_id,
                service_label=show_service,
                product_title=show_product,
                offer_price=show_price,
            )
            if smtp_block_bounce and chunks:
                from services.smtp_block_control import smtp_removed_from_mailing_notice_html

                chunks[0] += smtp_removed_from_mailing_notice_html()

            if not mail_db_id:
                try:
                    async with _imap_db_session() as session:
                        row_id = (
                            await session.execute(
                                sa_select(IncomingMail.id)
                                .where(IncomingMail.account_id == int(acc_id))
                                .where(IncomingMail.imap_uid == int(uid_num))
                                .order_by(IncomingMail.id.desc())
                                .limit(1)
                            )
                        ).scalar_one_or_none()
                        if row_id:
                            mail_db_id = int(row_id)
                except Exception:
                    logger.exception(
                        "Failed to resolve mail_db_id for kb acc=%s uid=%s", acc_id, uid_key
                    )

            kb = build_kb(acc_id, uid_key, mail_id=mail_db_id)

            # ✅ ТЗ: повторные письма от продавца крепятся к первому ответу (и лиду) того же продавца.
            reply_to_id: int | None = None
            try:
                async with _imap_db_session() as _s_anchor:
                    reply_to_id = await seller_thread_tg_anchor_message_id(
                        _s_anchor,
                        user_id=int(user_id),
                        account_id=int(acc_id),
                        from_email=str(from_email_clean).strip(),
                        conv=conv,
                    )
            except Exception:
                reply_to_id = None
                try:
                    if conv and getattr(conv, "tg_message_id", None):
                        reply_to_id = int(conv.tg_message_id)
                except Exception:
                    reply_to_id = None

            if chunks:
                claimed_notify = False
                if mail_db_id:
                    try:
                        async with _imap_db_session() as session:
                            await _release_stale_telegram_notify_claims(session)
                            await _acquire_incoming_notify_lock(
                                session,
                                user_id=int(user_id),
                                account_id=int(acc_id),
                                from_email=from_email_clean,
                                body=body_clean or "",
                            )
                            dup_tid = await _wait_duplicate_telegram_notify(
                                session,
                                mail_db_id=int(mail_db_id),
                                user_id=int(user_id),
                                account_id=int(acc_id),
                                from_email=from_email_clean,
                                subject=subject or "",
                                body=body_clean or "",
                            )
                            if dup_tid == -1:
                                await _release_stale_telegram_notify_claims(session)
                                await _release_telegram_notify_claim(session, int(mail_db_id))
                                dup_tid = None
                            if dup_tid and int(dup_tid) > 0:
                                await session.execute(
                                    update(IncomingMail)
                                    .where(IncomingMail.id == int(mail_db_id))
                                    .values(telegram_message_id=int(dup_tid))
                                )
                                await _db_commit_retry(session)
                                forwarded += 1
                                continue
                            claimed_notify = await _try_claim_telegram_notify(
                                session, int(mail_db_id)
                            )
                            if not claimed_notify:
                                await asyncio.sleep(0.5)
                                claimed_notify = await _try_claim_telegram_notify(
                                    session, int(mail_db_id)
                                )
                            if not claimed_notify:
                                logger.warning(
                                    "telegram notify claim lost mail_id=%s from=%s — skip TG",
                                    mail_db_id,
                                    from_email_clean,
                                )
                                forwarded += 1
                                continue
                    except Exception:
                        logger.exception(
                            "telegram notify claim failed mail_id=%s", mail_db_id
                        )
                        forwarded += 1
                        continue

                try:
                    m = await bot.send_message(
                        chat_id=tg_id,
                        text=chunks[0],
                        reply_markup=kb,
                        parse_mode="HTML",
                        reply_to_message_id=reply_to_id,
                        disable_web_page_preview=True,
                    )
                except Exception:
                    if mail_db_id and claimed_notify:
                        try:
                            async with _imap_db_session() as session:
                                await _release_telegram_notify_claim(
                                    session, int(mail_db_id)
                                )
                        except Exception:
                            pass
                    raise
            else:
                m = await bot.send_message(
                    chat_id=tg_id,
                    text="—",
                    reply_markup=kb,
                    parse_mode="HTML",
                    reply_to_message_id=reply_to_id,
                    disable_web_page_preview=True,
                )

            if mail_db_id:
                try:
                    async with _imap_db_session() as session:
                        mail_row = (
                            await session.execute(
                                sa_select(IncomingMail).where(IncomingMail.id == int(mail_db_id)).limit(1)
                            )
                        ).scalars().first()
                        if mail_row:
                            mail_row.telegram_message_id = int(m.message_id)
                            if offer_id:
                                from services.offer_storage import live_user_offer

                                live = await live_user_offer(
                                    session,
                                    user_id=int(mail_row.user_id),
                                    offer_id=int(offer_id),
                                )
                                if live:
                                    mail_row.resolved_offer_id = int(live.id)
                                    mail_row.mailing_bound = True
                            await _db_commit_retry(session)
                except Exception:
                    logger.exception(
                        "Failed to persist telegram_message_id mail_id=%s", mail_db_id
                    )

            # Карточка письма в TG — anchor для ответов «Написать ещё» (не только FSM).
            try:
                FULL_META[(acc_id, uid_key)]["tg_card_message_id"] = int(m.message_id)
            except Exception:
                pass

            # Если это первое сообщение в диалоге — пинуем и сохраняем anchor message_id.
            try:
                if reply_to_id is None:
                    await _try_pin(bot, tg_id, m.message_id)
                    await _upsert_convlink(
                        user_id=user_id,
                        inbox_email=_canon_email(inbox_email_clean),
                        contact_email=_canon_email(from_email_clean),
                        tg_message_id=int(m.message_id),
                    )
            except Exception:
                pass

            if photo_to_send:
                try:
                    await bot.send_photo(
                        chat_id=tg_id,
                        photo=photo_to_send,
                        caption=photo_caption
                        or format_first_incoming_photo_caption(
                            product_title=product_title,
                            offer_price=offer_price,
                        ),
                        parse_mode="HTML",
                        reply_to_message_id=int(m.message_id),
                    )
                except Exception:
                    logger.exception(
                        "send_photo failed tg=%s url=%s",
                        tg_id,
                        (photo_to_send or "")[:120],
                    )

            forwarded += 1

        except Exception:
            logger.exception("Failed to forward incoming email acc=%s uid=%s", acc_id, uid)

    return forwarded


_IDLE_TASKS: Dict[int, asyncio.Task] = {}
_IDLE_STOPS: Dict[int, threading.Event] = {}
_EVENT_QUEUES: Dict[int, asyncio.Queue] = {}

_ACCOUNTS_MAP_CACHE: tuple[list[tuple[EmailAccount, int]], float] | None = None
_ACCOUNTS_MAP_CACHE_TTL_SEC = float(_os.getenv("IMAP_ACCOUNTS_CACHE_SEC", "30"))
_MAX_IMAP_CONCURRENT = max(8, min(32, int(_os.getenv("MAX_IMAP_CONCURRENT", "24"))))
# per_user — не опрашивать ящики того, кто шлёт /send
# slow — опрос реже при рассылке (почта приходит, бот не душится)
# off — без замедления; all — пауза для всех
_IMAP_MAILING_PAUSE = (__import__("os").getenv("IMAP_MAILING_PAUSE", "off") or "off").strip().lower()
_IMAP_POLL_SECONDS_MAILING = max(30, int(__import__("os").getenv("INCOMING_MAIL_POLL_SECONDS_MAILING", "90")))
_IMAP_MAX_CONCURRENT_MAILING = max(1, int(__import__("os").getenv("MAX_IMAP_CONCURRENT_MAILING", "4")))
_IMAP_BATCH_YIELD_SEC = max(0.0, float(__import__("os").getenv("IMAP_BATCH_YIELD_SEC", "0.08")))
_IMAP_SLOT_SEM: asyncio.Semaphore | None = None


def _imap_slot_sem() -> asyncio.Semaphore:
    global _IMAP_SLOT_SEM
    if _IMAP_SLOT_SEM is None:
        _IMAP_SLOT_SEM = asyncio.Semaphore(_MAX_IMAP_CONCURRENT)
    return _IMAP_SLOT_SEM


async def _refresh_accounts_map() -> list[tuple[EmailAccount, int]]:
    global _ACCOUNTS_MAP_CACHE
    now = _now()
    if _ACCOUNTS_MAP_CACHE is not None:
        cached, ts = _ACCOUNTS_MAP_CACHE
        if (now - ts) < _ACCOUNTS_MAP_CACHE_TTL_SEC:
            return cached

    async with _imap_db_session() as session:
        accounts = (await session.execute(
            sa_select(EmailAccount).where(
                sa_or(
                    EmailAccount.status.is_(None),
                    EmailAccount.status.in_(["active", "enabled", "proxy_error", "smtp_blocked"]),
                )
            )
        )).scalars().all()

        users = (await session.execute(sa_select(User))).scalars().all()
        users_by_id = {u.id: u.telegram_id for u in users}

    out: list[tuple[EmailAccount, int]] = []
    for a in accounts:
        tg_id = users_by_id.get(a.user_id)
        if tg_id:
            out.append((a, int(tg_id)))
    _ACCOUNTS_MAP_CACHE = (out, now)
    return out


def invalidate_accounts_cache() -> None:
    """Сброс кэша списка ящиков (после добавления/удаления аккаунта)."""
    global _ACCOUNTS_MAP_CACHE
    _ACCOUNTS_MAP_CACHE = None


def _idle_thread_loop(
    acc_snapshot: dict[str, Any],
    start_last_uid: Optional[int],
    stop_evt: threading.Event,
    push_event: callable,
) -> None:
    last_uid = start_last_uid
    host, port = _imap_connect(acc_snapshot.get("provider") or "", acc_snapshot.get("email") or "")
    email_addr = str(acc_snapshot.get("email") or "")
    password = str(acc_snapshot.get("password") or "")

    M: Optional[imaplib.IMAP4_SSL] = None
    idle_ok = False

    while not stop_evt.is_set():
        try:
            if M is None:
                M = _imap_connect_and_select(host, port, email_addr, password)
                idle_ok = _imap_supports_idle(M)

                if last_uid is None:
                    _, max_uid0 = _imap_fetch_new_sync_raw(
                        host=host, port=port, email_addr=email_addr, password=password, last_uid=None
                    )
                    last_uid = max_uid0

            if USE_IMAP_IDLE and idle_ok:
                _imap_idle_wait_sync(M, IDLE_TIMEOUT_SEC)
            else:
                time.sleep(POLL_FALLBACK_SEC)

            mails, new_last = _imap_fetch_new_sync_raw(
                host=host, port=port, email_addr=email_addr, password=password, last_uid=last_uid
            )
            if new_last is not None:
                last_uid = int(new_last)

            if mails:
                push_event({"type": "mails", "mails": mails, "last_uid": last_uid})

        except Exception as e:
            if _is_invalid_credentials_error(e):
                push_event({"type": "invalid_creds", "error": str(e)})
                return

            try:
                if M is not None:
                    try:
                        M.logout()
                    except Exception:
                        pass
            finally:
                M = None

            push_event({"type": "error", "error": str(e)})
            time.sleep(2)

    try:
        if M is not None:
            M.logout()
    except Exception:
        pass


async def _start_idle_for_account(bot: Bot, acc: EmailAccount, tg_id: int) -> None:
    acc_id = int(acc.id)
    if acc_id in _IDLE_TASKS and not _IDLE_TASKS[acc_id].done():
        return

    stop_evt = threading.Event()
    q: asyncio.Queue = asyncio.Queue(maxsize=200)
    _IDLE_STOPS[acc_id] = stop_evt
    _EVENT_QUEUES[acc_id] = q

    loop = asyncio.get_running_loop()

    snap = {
        "id": acc_id,
        "user_id": int(acc.user_id),
        "email": str(acc.email),
        "password": str(acc.password or ""),
        "provider": str(getattr(acc, "provider", "") or ""),
    }

    start_last = getattr(acc, "last_seen_uid", None)
    if start_last is None:
        start_last = LAST_UID.get(acc_id)

    def push_event(item: dict[str, Any]) -> None:
        try:
            loop.call_soon_threadsafe(q.put_nowait, item)
        except Exception:
            pass

    async def _runner():
        sem = _imap_slot_sem()
        await sem.acquire()
        thread_task: asyncio.Task | None = None
        try:
            thread_task = asyncio.create_task(
                asyncio.to_thread(_idle_thread_loop, snap, start_last, stop_evt, push_event)
            )

            while not stop_evt.is_set():
                item = await q.get()
                typ = item.get("type")

                if typ == "mails":
                    mails = item.get("mails") or []
                    last_uid = item.get("last_uid")
                    await _process_mails_for_account(
                        bot,
                        acc_id=acc_id,
                        tg_id=tg_id,
                        user_id=int(snap["user_id"]),
                        account_email=str(snap["email"]),
                        mails=mails,
                        max_per_account=DEFAULT_MAX_PER_ACCOUNT,
                        last_uid=last_uid,
                    )
                    _ERROR_STREAK.pop(acc_id, None)
                    _BACKOFF_UNTIL.pop(acc_id, None)

                elif typ == "invalid_creds":
                    stop_evt.set()
                    break

                elif typ == "error":
                    err_txt = str(item.get("error") or "")

                    if _is_transient_ssl_eof(Exception(err_txt)):
                        delay = 2
                        _ERROR_STREAK[acc_id] = 1
                        _BACKOFF_UNTIL[acc_id] = _now() + delay

                        last_log = _LAST_EOF_LOG.get(acc_id, 0.0)
                        if _now() - last_log >= _EOF_LOG_COOLDOWN_SEC:
                            _LAST_EOF_LOG[acc_id] = _now()
                            logger.info(
                                "IMAP reconnect acc=%s email=%s (EOF/TLS reset)",
                                acc_id, snap["email"]
                            )
                        await asyncio.sleep(delay)
                        continue

                    streak = int(_ERROR_STREAK.get(acc_id, 0)) + 1
                    _ERROR_STREAK[acc_id] = streak
                    delay = _calc_backoff(streak)
                    _BACKOFF_UNTIL[acc_id] = _now() + delay

                    logger.warning(
                        "IMAP error acc=%s email=%s backoff=%ss err=%s",
                        acc_id, snap["email"], delay, err_txt
                    )
                    await asyncio.sleep(min(3, delay))

        finally:
            stop_evt.set()
            if thread_task is not None:
                try:
                    thread_task.cancel()
                except Exception:
                    pass
            sem.release()

    _IDLE_TASKS[acc_id] = asyncio.create_task(_runner())


async def _cancel_legacy_idle_tasks() -> None:
    """Старый режим: по потоку на ящик навсегда — отключаем при round-robin scheduler."""
    for stop_evt in list(_IDLE_STOPS.values()):
        stop_evt.set()
    for task in list(_IDLE_TASKS.values()):
        if not task.done():
            task.cancel()
    _IDLE_STOPS.clear()
    _EVENT_QUEUES.clear()
    _IDLE_TASKS.clear()


def _eligible_accounts_for_poll(
    accounts: list[tuple[EmailAccount, int]],
    *,
    now: float,
    mailing_tg_ids: frozenset[int],
) -> list[tuple[EmailAccount, int]]:
    mode = _IMAP_MAILING_PAUSE
    if mode == "all" and mailing_tg_ids:
        return []
    out: list[tuple[EmailAccount, int]] = []
    for acc, tg_id in accounts:
        if mode == "per_user" and int(tg_id) in mailing_tg_ids:
            continue
        acc_id = int(acc.id)
        until = _BACKOFF_UNTIL.get(acc_id)
        if until and now < float(until):
            continue
        last_poll = _LAST_POLL_AT.get(acc_id, 0.0)
        if last_poll and (now - float(last_poll)) < float(IMAP_PER_ACCOUNT_INTERVAL_SEC):
            continue
        out.append((acc, int(tg_id)))
    out.sort(key=lambda it: float(_LAST_POLL_AT.get(int(it[0].id), 0.0)))
    return out


async def _poll_account_once(bot: Bot, acc: EmailAccount, tg_id: int) -> None:
    """Один IMAP-опрос ящика: слот семафора только на время сетевого fetch (не навсегда)."""
    acc_id = int(acc.id)
    email_addr = str(acc.email or "")
    password = str(acc.password or "")
    provider = str(getattr(acc, "provider", "") or "")
    user_id = int(acc.user_id)
    host, port = _imap_connect(provider, email_addr)

    last_uid = getattr(acc, "last_seen_uid", None)
    if last_uid is None:
        last_uid = LAST_UID.get(acc_id)

    sem = _imap_slot_sem()
    await sem.acquire()
    polled_at = _now()
    try:
        mails, new_last = await asyncio.wait_for(
            asyncio.to_thread(
                _imap_fetch_new_sync_raw,
                host=host,
                port=port,
                email_addr=email_addr,
                password=password,
                last_uid=last_uid,
            ),
            timeout=float(IMAP_ACCOUNT_TIMEOUT_SEC),
        )
    except asyncio.TimeoutError:
        streak = int(_ERROR_STREAK.get(acc_id, 0)) + 1
        _ERROR_STREAK[acc_id] = streak
        delay = _calc_backoff(streak)
        _BACKOFF_UNTIL[acc_id] = _now() + delay
        _LAST_POLL_AT[acc_id] = polled_at
        logger.warning(
            "IMAP timeout acc=%s email=%s (%ss) backoff=%ss",
            acc_id,
            email_addr,
            IMAP_ACCOUNT_TIMEOUT_SEC,
            delay,
        )
        return
    except Exception as e:
        if _is_invalid_credentials_error(e):
            _LAST_POLL_AT[acc_id] = polled_at
            logger.warning("IMAP invalid creds acc=%s email=%s", acc_id, email_addr)
            return

        if _is_transient_ssl_eof(e):
            delay = 2
            _ERROR_STREAK[acc_id] = 1
            _BACKOFF_UNTIL[acc_id] = _now() + delay
            _LAST_POLL_AT[acc_id] = polled_at
            last_log = _LAST_EOF_LOG.get(acc_id, 0.0)
            if _now() - last_log >= _EOF_LOG_COOLDOWN_SEC:
                _LAST_EOF_LOG[acc_id] = _now()
                logger.info("IMAP reconnect acc=%s email=%s (EOF/TLS reset)", acc_id, email_addr)
            return

        streak = int(_ERROR_STREAK.get(acc_id, 0)) + 1
        _ERROR_STREAK[acc_id] = streak
        delay = _calc_backoff(streak)
        _BACKOFF_UNTIL[acc_id] = _now() + delay
        _LAST_POLL_AT[acc_id] = polled_at
        logger.warning(
            "IMAP error acc=%s email=%s backoff=%ss err=%s",
            acc_id,
            email_addr,
            delay,
            e,
        )
        return
    finally:
        sem.release()

    if new_last is not None:
        LAST_UID[acc_id] = int(new_last)
        await _set_last_seen_uid(acc_id, int(new_last))

    if mails:
        await _process_mails_for_account(
            bot,
            acc_id=acc_id,
            tg_id=tg_id,
            user_id=user_id,
            account_email=email_addr,
            mails=mails,
            max_per_account=DEFAULT_MAX_PER_ACCOUNT,
            last_uid=new_last,
        )

    _ERROR_STREAK.pop(acc_id, None)
    _BACKOFF_UNTIL.pop(acc_id, None)
    _LAST_POLL_AT[acc_id] = polled_at


async def _mailing_telegram_ids() -> frozenset[int]:
    from services.sending_state import active_mailing_telegram_ids
    from services.mailing_active_db import mailing_telegram_ids_from_db

    return active_mailing_telegram_ids() | await mailing_telegram_ids_from_db()


async def _poll_accounts_batch(
    bot: Bot,
    batch: list[tuple[EmailAccount, int]],
    *,
    max_concurrent: int | None = None,
) -> None:
    if not batch:
        return
    limit = max_concurrent or _MAX_IMAP_CONCURRENT
    chunk = batch[:limit]
    results = await asyncio.gather(
        *[_poll_account_once(bot, acc, tg_id) for acc, tg_id in chunk],
        return_exceptions=True,
    )
    for r in results:
        if isinstance(r, Exception):
            logger.exception("IMAP poll task failed: %s", r)


async def _idle_manager_loop(bot: Bot, *, poll_seconds: int) -> None:
    global _SCHEDULER_LAST_TICK
    await _cancel_legacy_idle_tasks()
    per_acc = max(int(poll_seconds), IMAP_PER_ACCOUNT_INTERVAL_SEC)
    logger.info(
        "IMAP scheduler: per_account_interval=%ss cycle_sleep=%ss max_concurrent=%s "
        "account_timeout=%ss connect_timeout=%ss pause_mode=%s",
        per_acc,
        IMAP_CYCLE_SLEEP_SEC,
        _MAX_IMAP_CONCURRENT,
        IMAP_ACCOUNT_TIMEOUT_SEC,
        IMAP_CONNECT_TIMEOUT_SEC,
        _IMAP_MAILING_PAUSE,
    )

    while True:
        _SCHEDULER_LAST_TICK = _now()
        await _maybe_persist_imap_diag()
        cycle_pause = IMAP_CYCLE_SLEEP_SEC
        polled_this_cycle = 0
        try:
            mailing = await _mailing_telegram_ids()
            effective_max = _MAX_IMAP_CONCURRENT

            if _IMAP_MAILING_PAUSE == "all" and mailing:
                logger.info(
                    "IMAP: пауза для всех — рассылка у tg=%s (режим all)",
                    ",".join(str(x) for x in sorted(mailing)[:5]),
                )
                await asyncio.sleep(max(5, cycle_pause))
                continue

            if mailing and _IMAP_MAILING_PAUSE == "slow":
                cycle_pause = max(cycle_pause, min(_IMAP_POLL_SECONDS_MAILING, 60))
                effective_max = min(effective_max, _IMAP_MAX_CONCURRENT_MAILING)
                logger.info(
                    "IMAP: slow mode — рассылка tg=%s, пауза цикла %ss, concurrent=%s",
                    ",".join(str(x) for x in sorted(mailing)[:3]),
                    cycle_pause,
                    effective_max,
                )

            now = _now()
            accounts = await _refresh_accounts_map()
            eligible = _eligible_accounts_for_poll(accounts, now=now, mailing_tg_ids=mailing)

            if mailing and _IMAP_MAILING_PAUSE == "per_user":
                skipped = len(accounts) - len(eligible)
                if skipped:
                    logger.debug(
                        "IMAP: пропуск %s ящиков (рассылка у %s пользов.)",
                        skipped,
                        len(mailing),
                    )

            if not eligible:
                await asyncio.sleep(2)
                continue

            # Одна волна за тик — планировщик не зависает на 200 ящиках, тик каждые ~2–8с.
            wave = eligible[:effective_max]
            await _poll_accounts_batch(bot, wave, max_concurrent=effective_max)
            polled_this_cycle = len(wave)
            if polled_this_cycle:
                logger.info(
                    "IMAP wave: polled %s due=%s mailboxes=%s interval=%ss conc=%s",
                    polled_this_cycle,
                    len(eligible),
                    len(accounts),
                    IMAP_PER_ACCOUNT_INTERVAL_SEC,
                    effective_max,
                )

        except Exception:
            logger.exception("Incoming mail manager loop error")

        await asyncio.sleep(max(1, cycle_pause))


async def _maybe_persist_imap_diag() -> None:
    """Пульс отдельного IMAP-сервиса → Postgres (для /imap_diag на newbot)."""
    global _last_diag_persist_at
    now = _now()
    if now - _last_diag_persist_at < _DIAG_PERSIST_INTERVAL_SEC:
        return
    _last_diag_persist_at = now
    try:
        import json
        import os

        from services.settings import set_setting

        diag = incoming_mail_diag_snapshot()
        diag["worker_role"] = (os.getenv("APP_ROLE") or "incoming_mail").strip()
        diag["persisted_at"] = now
        diag["worker_host"] = (
            os.getenv("RAILWAY_SERVICE_NAME")
            or os.getenv("RAILWAY_REPLICA_ID")
            or os.getenv("HOSTNAME")
            or "?"
        )
        async with _imap_db_session() as session:
            await set_setting(
                session,
                IMAP_DIAG_DB_KEY,
                json.dumps(diag, ensure_ascii=False),
            )
    except Exception:
        logger.debug("persist imap diag failed", exc_info=True)


async def load_imap_diag_from_db(session) -> dict[str, Any] | None:
    import json

    from services.settings import get_setting

    raw = await get_setting(session, IMAP_DIAG_DB_KEY)
    if not raw:
        return None
    try:
        data = json.loads(raw)
        if not isinstance(data, dict):
            return None
        if data.get("persisted_at"):
            data["remote_heartbeat_ago_sec"] = max(0, int(_now() - float(data["persisted_at"])))
        return data
    except Exception:
        return None


async def incoming_mail_diag_merged(session) -> dict[str, Any]:
    """Локальный воркер или снимок из БД (отдельный imap-worker на Railway)."""
    local = incoming_mail_diag_snapshot()
    tick = local.get("scheduler_last_tick_ago_sec")
    if tick is not None and int(tick) < 300:
        local["diag_source"] = "local_process"
        return local

    remote = await load_imap_diag_from_db(session)
    if remote:
        ago = remote.get("remote_heartbeat_ago_sec")
        if ago is not None and int(ago) < 600:
            remote["diag_source"] = "dedicated_worker"
            return remote

    local["diag_source"] = "no_active_worker"
    return local


def incoming_mail_diag_snapshot() -> dict[str, Any]:
    """Снимок для /imap_diag (без секретов)."""
    now = _now()
    backoff: dict[int, int] = {}
    for aid, until in list(_BACKOFF_UNTIL.items()):
        if float(until) > now:
            backoff[int(aid)] = max(0, int(float(until) - now))
    due_soon = 0
    for aid, ts in list(_LAST_POLL_AT.items()):
        if (now - float(ts)) >= float(IMAP_PER_ACCOUNT_INTERVAL_SEC) * 0.9:
            due_soon += 1
    return {
        "poll_fallback_sec": int(POLL_FALLBACK_SEC),
        "scheduler": "round_robin_per_account",
        "per_account_interval_sec": int(IMAP_PER_ACCOUNT_INTERVAL_SEC),
        "cycle_sleep_sec": int(IMAP_CYCLE_SLEEP_SEC),
        "account_timeout_sec": int(IMAP_ACCOUNT_TIMEOUT_SEC),
        "max_concurrent": _MAX_IMAP_CONCURRENT,
        "mailing_pause": _IMAP_MAILING_PAUSE,
        "legacy_idle_threads": len(_IDLE_TASKS),
        "tracked_mailboxes": len(_LAST_POLL_AT),
        "due_for_poll_approx": due_soon,
        "scheduler_last_tick_ago_sec": int(now - _SCHEDULER_LAST_TICK) if _SCHEDULER_LAST_TICK else None,
        "backoff_sec_by_account": backoff,
        "error_streak_by_account": {int(k): int(v) for k, v in _ERROR_STREAK.items()},
    }


def start_incoming_mail_worker(bot: Bot, poll_seconds: int = 35) -> None:
    global _worker_task
    if _worker_task and not _worker_task.done():
        return

    async def _loop():
        await _idle_manager_loop(bot, poll_seconds=poll_seconds)

    _worker_task = asyncio.create_task(_loop())
    logger.info(
        "Incoming mail worker started: per_account~%ss cycle_sleep=%ss max_concurrent=%s pause=%s",
        IMAP_PER_ACCOUNT_INTERVAL_SEC,
        IMAP_CYCLE_SLEEP_SEC,
        _MAX_IMAP_CONCURRENT,
        _IMAP_MAILING_PAUSE,
    )
