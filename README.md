# GAG Bot (Швейцария)

Отдельный Telegram-бот для команды **GAG** — валидация + **burst-рассылка** с максимальной доходимостью.

## Inbox placement (Inbox получателя, не Spam)

**SMTP 250 ≠ Inbox.** Письмо может быть «принято» Gmail SMTP, но попасть в Spam у продавца.

Бот настроен под **Inbox placement**:

| Механизм | Зачем |
|---|---|
| Plain text only | HTML-multipart чаще в Spam на cold mail |
| Без URL в 1-м письме | Ссылка — в ответе/HTML после ответа продавца |
| Без ложного `Re:` в теме | Фильтры режут fake reply |
| Уник. тема + текст + подпись | Не один шаблон на 100 адресов |
| Stagger ящиков (150 ms) | Не залп с 50 Gmail за 0.1 с |
| Gap на ящик (2.5 s) | Если адресов больше, чем ящиков |
| Minimal From | `from@gmail.com` без marketing-имени |
| Validemail strict | Только живые адреса в очереди |

**Важно для Inbox:**
- Прогретые Gmail (не свежие)
- Ротационный **residential** SOCKS5
- Запуск с **VPS/ПК**, не Railway (EHLO fingerprint) — `MAILING_EHLO_NAME`
- Сначала **Тест маил** на свой ящик → Inbox или Spam

```env
INBOX_STAGGER_MS=150
INBOX_ACCOUNT_GAP_SEC=2.5
MAILING_EHLO_NAME=localhost
```

## Premium emoji в кнопках

Заполните `config/premium_emoji.json` ID из Telegram Premium (или env `EMOJI_SEND=123…`).

Как получить ID:
1. Перешлите premium-emoji боту [@RawDataBot](https://t.me/RawDataBot) или посмотрите `custom_emoji_id` в update
2. Вставьте в JSON: `"send": "5440123456789012345"`

Без ID — fallback на обычные Unicode (в логе будет warning).

## Запуск

```bash
cd C:\Users\user\Projects\gag-bot
pip install -r requirements.txt
copy .env.example .env
python bot.py
```

## .env минимум

```env
BOT_TOKEN=
GAG_TEAM_API_KEY=
VALIDEMAIL_API_KEYS=
```

## Burst-рассылка

- Один ротирующий SOCKS5
- Параллельно по всем active Gmail
- Цель: **2–5 с** на всю очередь (≈ 1 ящик = 1 параллельное письмо)
- SMTP 250 + NOOP, без IMAP-проверки (скорость)

## API

Сервисы: `ricardo_ch`, `tutti.ch` → `tutti_ch`. Личный ключ: ⚙️ → 🔑.
