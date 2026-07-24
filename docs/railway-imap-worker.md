# Railway: newbot + отдельный IMAP worker

Один репозиторий, **два сервиса**, одна **PostgreSQL**.

| Сервис | Start Command | Роль |
|--------|---------------|------|
| **newbot** | `python bot.py` | Telegram, рассылка, валидация, ответы |
| **imap-worker** | `python imap_worker.py` | Только опрос IMAP → карточки в TG |

Оба используют **один `BOT_TOKEN`** (polling только на newbot; IMAP шлёт `send_message`).

## 1. Postgres

Уже есть → `DATABASE_URL` = `${{Postgres.DATABASE_URL}}` на **обоих** сервисах.

## 2. Сервис newbot (основной)

**Settings → Deploy → Custom Start Command:** `python bot.py` (или из `railway.toml`).

**Variables:**

```env
BOT_TOKEN=...
DATABASE_URL=${{Postgres.DATABASE_URL}}
ENV=production
IMAP_DEDICATED_WORKER=1
```

Не включай `ENABLE_INCOMING_MAIL` на newbot.

Остальное как раньше: `GAG_API_BASE`, `VALIDEMAIL_API_KEYS`, прокси и т.д.

## 3. Новый сервис imap-worker

1. Project → **+ New** → **GitHub Repo** → тот же репозиторий `newbot`.
2. Переименуй сервис, например **imap-worker**.
3. **Settings → Deploy → Custom Start Command:**
   ```bash
   python imap_worker.py
   ```
4. **Variables** (минимум):

```env
BOT_TOKEN=${{newbot.BOT_TOKEN}}
DATABASE_URL=${{Postgres.DATABASE_URL}}
ENV=production
ENABLE_INCOMING_MAIL=1
APP_ROLE=imap_worker
```

`BOT_TOKEN` можно reference с newbot или вставить тот же токен.

**Опционально (дефолты уже в imap_worker.py):**

```env
INCOMING_MAIL_POLL_SECONDS=120
MAX_IMAP_CONCURRENT=20
IMAP_PER_ACCOUNT_INTERVAL_SEC=120
IMAP_MAILING_PAUSE=per_user
```

5. **Deploy** оба сервиса.

## 4. Проверка

**imap-worker → Logs:**

- `IMAP worker: PostgreSQL …`
- `IMAP worker running`
- каждые ~60s: `💓 IMAP worker #N`

**newbot → Logs:**

- `IMAP на отдельном сервисе … IMAP_DEDICATED_WORKER=1`
- нет `Incoming mail worker стартовал` на newbot

**Telegram:** `/imap_diag` → строка `Воркер: dedicated_worker · imap-worker …`

## 5. Ошибки

| Симптом | Причина |
|---------|---------|
| `TelegramConflictError` на newbot | Два процесса с polling (второй `bot.py`) |
| Нет входящих | `ENABLE_INCOMING_MAIL=1` только на imap-worker |
| IMAP и на боте, и на воркере | Убери `ENABLE_INCOMING_MAIL` с newbot, добавь `IMAP_DEDICATED_WORKER=1` |
| `/imap_diag` → `no_active_worker` | imap-worker не запущен или нет связи с Postgres |
