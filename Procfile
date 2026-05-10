release: python manage.py migrate --noinput && python manage.py collectstatic --noinput
web: gunicorn config.wsgi --bind 0.0.0.0:$PORT --workers ${WEB_CONCURRENCY:-4} --worker-class sync --timeout 120 --max-requests 1000 --max-requests-jitter 100
worker: celery -A config worker -Q default --concurrency=${CELERY_CONCURRENCY:-4} --loglevel=info
ai_worker: celery -A config worker -Q ai --concurrency=${AI_CONCURRENCY:-2} --loglevel=info --max-tasks-per-child=5
