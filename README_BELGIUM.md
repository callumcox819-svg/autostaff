# Belgium Bot (Narkologia)

Отдельный Telegram-бот для рассылки по Бельгии. Основа — `finland-bot` / `happy88-main`, адаптирована под команду **Narkologia** и [APEX API](https://docs.domainforapi.com/docs/getting-started/introduction).

## Регион

- Страна: **Бельгия (BE)**
- Площадка: **2dehands.be**
- Команда: **Narkologia**
- Сервисы API: `2dehands_be`, `bpost_be`
- HTML-шаблоны: `data/HTMLbe/`

## API Narkologia

- Домен: `https://traffic.withhatetoapi.cc` (резерв: `https://domainforapi.com`)
- Авторизация: `Authorization: Bearer <личный токен>`, `X-Team-Key: <токен команды>`
- Генерация ссылки: `POST /api/order/generate/lonely` (или `/lonely/parser` с URL объявления)
- Профиль в боте (имя + адрес) передаётся в поля `user` и `address` при каждой генерации

## Переменные окружения

| Переменная | Описание |
|---|---|
| `BOT_TOKEN` | Telegram Bot API token |
| `ADMIN_IDS` | ID админов через запятую |
| `DATABASE_URL` | Postgres (Railway) или пусто → SQLite локально |
| `NARKOLOGIA_TEAM_API_KEY` | Токен команды (X-Team-Key) из панели Narkologia |
| `NARKOLOGIA_API_BASE` | Опционально; по умолчанию traffic.withhatetoapi.cc |

Личный API key каждый пользователь задаёт в боте: ⚙️ → 🔑 → «Личный API key» (поле «Ваш токен» в Narkologia).

## Фаст-рассыл + ротирующий SOCKS5

Для **максимальной скорости** и **одного ротирующего прокси** (gateway сам меняет IP):

1. В «Прокси» добавьте **один** SOCKS5 gateway (формат `socks5://user:pass@host:port`).
2. В ⚙️ Настройки включите **🟢 Фаст рассыл** (по умолчанию включён, если `DEFAULT_FAST_MAILING=1`).
3. Запустите `/send` — все active Gmail-ящики шлют **параллельно** через один gateway; каждое новое SMTP-соединение = новый IP.
4. Опционально в `.env`: `ROTATING_PROXY_ID=<id>` если в списке несколько прокси.

Скорость ≈ число active ящиков × 1 письмо за волну (без пауз между волнами). 20 ящиков + 20 email ≈ 3–8 секунд при успешном SMTP.

| Переменная | Значение по умолчанию | Описание |
|---|---|---|
| `DEFAULT_FAST_MAILING` | `1` | Фаст-режим для новых пользователей |
| `MAIL_FAST_SMTP_TIMEOUT_SEC` | `22` | Таймаут SMTP в фаст-режиме |
| `MAIL_FAST_PARALLEL_ACCOUNTS` | `0` | `0` = все ящики параллельно |
| `MAIL_FAST_PREFLIGHT_TIMEOUT` | `12` | Быстрая проверка 1 gateway перед стартом |
| `ROTATING_PROXY_ID` | — | Явный id ротирующего SOCKS5 в БД |

Обычный режим (без фаста) по-прежнему крутит пул SOCKS5 до 10 попыток на письмо — для ротирующего gateway используйте только **фаст**.

## Локальный запуск

```bash
cd C:\Users\user\Projects\belgium-bot
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
# заполнить BOT_TOKEN и при необходимости ADMIN_IDS
python bot.py
```

## Деплой

См. `railway.toml` и `RAILWAY_IMAP_WORKER.txt` (как у finland-bot).
