#!/bin/sh
set -eu

python manage.py collectstatic --noinput

exec gunicorn config.wsgi:application \
  --bind "0.0.0.0:${PORT:-8080}" \
  --workers "${WEB_CONCURRENCY:-4}" \
  --worker-class sync \
  --timeout "${GUNICORN_TIMEOUT:-120}" \
  --max-requests "${GUNICORN_MAX_REQUESTS:-1000}" \
  --max-requests-jitter "${GUNICORN_MAX_REQUESTS_JITTER:-100}"