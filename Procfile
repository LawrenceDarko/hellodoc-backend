web: gunicorn config.wsgi --bind 0.0.0.0:$PORT --workers 2
worker: celery -A config worker --loglevel=info --concurrency=2
