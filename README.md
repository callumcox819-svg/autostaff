# GAG Bot — Швейцария

Telegram-бот для команды **GAG**: валидация email, **burst-рассылка**, входящие письма, генерация ссылок через GAG API.

Площадки: **ricardo.ch**, **tutti.ch**.

## Возможности

- Burst-рассылка: параллельно по всем Gmail, цель 2–5 с на очередь
- Inbox placement: plain text, без URL в первом письме, stagger между ящиками
- Один ротирующий SOCKS5-прокси
- Ротация Gmail-аккаунтов и текстов
- Premium emoji в кнопках (`config/premium_emoji.json`)
- HTML-шаблоны для ответов: `data/HTMLch/ricardo_ch/`, `data/HTMLch/tutti_ch/`

## Быстрый старт

```bash
cd gag-bot
pip install -r requirements.txt
copy .env.example .env
# заполните BOT_TOKEN, GAG_TEAM_API_KEY, VALIDEMAIL_API_KEYS
python bot.py
```

## .env

```env
BOT_TOKEN=
GAG_TEAM_API_KEY=
VALIDEMAIL_API_KEYS=
DATABASE_URL=          # опционально; без него — локальный SQLite
ROTATING_PROXY_ID=     # один SOCKS5 с ротацией IP
```

### Inbox placement

```env
MAILING_PLAIN_ONLY=1
MAILING_MINIMAL_HEADERS=1
MAILING_STRIP_LINK=1
INBOX_STAGGER_MS=150
INBOX_ACCOUNT_GAP_SEC=2.5
MAILING_EHLO_NAME=localhost
```

Рекомендуется запуск с VPS/ПК (не shared PaaS) для корректного EHLO.

## GAG API

Сервисы: `ricardo_ch`, `tutti_ch`. Личный ключ: ⚙️ → 🔑.

## Структура

```
bot.py              — точка входа
handlers/           — Telegram-команды
services/           — рассылка, API, IMAP, валидация
data/HTMLch/        — HTML-шаблоны CH
config/             — premium emoji
region.py           — CH/GAG настройки
```

## IMAP worker (опционально)

Отдельный процесс для входящей почты:

```bash
ENABLE_INCOMING_MAIL=1 python imap_worker.py
```

На основном боте: `IMAP_DEDICATED_WORKER=1`.

## Тесты

```bash
python -m unittest discover -s tests -p "test_*.py"
```
