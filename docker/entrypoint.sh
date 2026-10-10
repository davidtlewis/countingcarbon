#!/bin/sh
# Apply migrations before starting the app. Set SKIP_MIGRATE=1 to bypass,
# e.g. when running one-off management commands.
set -e

if [ "${SKIP_MIGRATE:-0}" != "1" ]; then
  python manage.py migrate --no-input
fi

exec "$@"
