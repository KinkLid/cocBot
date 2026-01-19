#!/bin/sh

set -eu

attempt=1
max_attempts=10
delay_seconds=2

rm -f /app/bot/db/migrations/versions/0006_notification_rules_and_users_list.py

while [ "$attempt" -le "$max_attempts" ]; do
  if alembic upgrade head; then
    break
  fi

  if [ "$attempt" -eq "$max_attempts" ]; then
    echo "Failed to run Alembic migrations after ${max_attempts} attempts." >&2
    exit 1
  fi

  echo "Waiting for database... retry ${attempt}/${max_attempts}" >&2
  attempt=$((attempt + 1))
  sleep "$delay_seconds"
done

exec python -m bot.main
