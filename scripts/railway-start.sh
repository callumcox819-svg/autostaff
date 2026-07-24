#!/usr/bin/env sh
# Railway: один startCommand в railway.toml, роль — через APP_ROLE.
# newbot: APP_ROLE пусто или bot
# imap-worker: APP_ROLE=imap_worker
set -e
role=$(printf '%s' "${APP_ROLE:-bot}" | tr '[:upper:]' '[:lower:]')
case "$role" in
  imap_worker | imap-worker | imap)
    exec python imap_worker.py
    ;;
  *)
    exec python bot.py
    ;;
esac
