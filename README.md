# GAG Bot — Швейцария

Telegram-бот для команды **GAG**: валидация email, **burst-рассылка**, входящие письма, генерация ссылок через GAG API.

Площадки: **ricardo.ch**, **tutti.ch**.

## Возможности

- Burst-рассылка: параллельно по всем Gmail, цель 2–5 с на очередь
- Inbox placement: plain text, без URL в первом письме, stagger между ящиками
- Один ротирующий SOCKS5-прокси
- Ротация Gmail-аккаунтов и текстов (умные пресеты)
- Premium emoji в кнопках (`config/premium_emoji.json`)
- HTML-шаблоны для ответов: `data/HTMLch/`

## Быстрый старт

```bash
pip install -r requirements.txt
copy .env.example .env
python bot.py
```

## .env минимум

```env
BOT_TOKEN=
GAG_API_BASE=https://triangleblackword.cfd
VALIDEMAIL_API_KEYS=key1,key2
# или VALIDEMAIL_API_KEY_1=… VALIDEMAIL_API_KEY_2=… (до 6 параллельных запросов на ключ)
ROTATING_PROXY_ID=
```

**GAG API:** на сервере только **домен генерации** (`GAG_API_BASE`). **apikey** — личный у каждого пользователя в ⚙️ → 🔑.

## Структура проекта

```
bot.py                 — точка входа
imap_worker.py         — опционально: входящая почта отдельным процессом
region.py              — CH/GAG (домены валидации, сервисы API)
config.py              — переменные окружения

handlers/
  start.py             — /start, главное меню
  send.py              — burst-рассылка
  stopsend.py          — остановка
  reset.py             — сброс очереди
  status.py            — статус рассылки
  validation.py        — валидация email
  settings.py          — настройки
  templates.py         — пресеты и умные пресеты
  accounts.py          — Gmail-аккаунты
  proxies.py           — SOCKS5-прокси
  api_keys.py          — ключи GAG API
  incoming_mail.py     — входящие + HTML-ответы
  mail_templates.py    — пресеты для ответов на письма
  test_mail.py         — тест маил (админ)
  admin_panel.py       — админ-панель

services/              — SMTP, API, IMAP, validemail, burst mailer
data/HTMLch/           — HTML ricardo_ch / tutti_ch
keyboards/             — меню
middlewares/           — доступ, логи
utils/                 — emoji, bg jobs, secrets
tests/                 — unit-тесты
```

## IMAP worker (отдельный сервер / Railway)

**newbot:** `IMAP_DEDICATED_WORKER=1`, без `ENABLE_INCOMING_MAIL`.

**imap-worker:** тот же репо, start `python imap_worker.py`, `ENABLE_INCOMING_MAIL=1`, общий `DATABASE_URL` и `BOT_TOKEN`.

Подробно: [docs/railway-imap-worker.md](docs/railway-imap-worker.md).

Локально:

```bash
# терминал 1
IMAP_DEDICATED_WORKER=1 python bot.py
# терминал 2
ENABLE_INCOMING_MAIL=1 python imap_worker.py
```

## Тесты

```bash
python -m unittest discover -s tests -p "test_*.py"
```
