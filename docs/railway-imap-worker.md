# Railway: newbot + отдельный IMAP worker

Один репозиторий, **два сервиса**, одна **PostgreSQL**.

| Сервис | `APP_ROLE` | Роль |
|--------|------------|------|
| **newbot** | `bot` или пусто | Telegram, рассылка |
| **imap-worker** | `imap_worker` | Только IMAP |

Start Command в UI **задаётся в `railway.toml`**: `sh scripts/railway-start.sh` — менять команду в UI не нужно, только **`APP_ROLE`** на каждом сервисе.

## 2. Сервис newbot (основной)

**Variables:**

```env
BOT_TOKEN=...
DATABASE_URL=${{Postgres.DATABASE_URL}}
ENV=production
IMAP_DEDICATED_WORKER=1
APP_ROLE=bot
```

Не включай `ENABLE_INCOMING_MAIL` на newbot.

## 3. Сервис imap-worker

1. Project → **+ New** → **GitHub Repo** → тот же репозиторий `newbot`.
2. Переименуй сервис, например **imap-worker**.
3. **Custom Start Command** будет из `railway.toml` (`sh scripts/railway-start.sh`) — это нормально.
4. **Variables** (минимум):

```env
BOT_TOKEN=${{newbot.BOT_TOKEN}}
DATABASE_URL=${{Postgres.DATABASE_URL}}
ENV=production
APP_ROLE=imap_worker
ENABLE_INCOMING_MAIL=1
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
