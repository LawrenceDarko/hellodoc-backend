from pathlib import Path
from datetime import timedelta
from django.core.exceptions import ImproperlyConfigured
from decouple import config, Csv
import dj_database_url

try:
    import sentry_sdk
except ModuleNotFoundError:
    sentry_sdk = None

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = config('SECRET_KEY')
DEBUG = config('DEBUG', default=False, cast=bool)
ALLOWED_HOSTS = config('ALLOWED_HOSTS', cast=Csv()) + ['testserver']
ENVIRONMENT = config('ENVIRONMENT', default='development')

if SECRET_KEY.startswith('your-') or len(SECRET_KEY) < 50:
    raise ImproperlyConfigured('SECRET_KEY is insecure')

if DEBUG and not config('ALLOW_DEBUG', cast=bool, default=False):
    raise ImproperlyConfigured('DEBUG must be False in production')

if sentry_sdk:
    sentry_sdk.init(
        dsn=config('SENTRY_DSN', default=''),
        traces_sample_rate=config('SENTRY_TRACES_RATE', cast=float, default=0.1),
        environment=ENVIRONMENT,
    )

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    # Third party
    'rest_framework',
    'rest_framework_simplejwt',
    'rest_framework_simplejwt.token_blacklist',
    'corsheaders',
    'django_celery_results',
    'storages',
    # HelloDoc apps
    'apps.core',
    'apps.users',
    'apps.patients',
    'apps.consultations',
    'apps.diagnosis',
]

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'
AUTH_USER_MODEL = 'users.User'
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

# Database
DATABASES = {
    'default': dj_database_url.config(default=config('DATABASE_URL'))
}
DATABASES['default']['CONN_MAX_AGE'] = 60
DATABASES['default']['CONN_HEALTH_CHECKS'] = True
# Production deployments should use PgBouncer for PostgreSQL connection pooling.

# DRF + JWT
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ),
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.IsAuthenticated',
    ),
    'DEFAULT_THROTTLE_CLASSES': (
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.UserRateThrottle',
    ),
    'DEFAULT_THROTTLE_RATES': {
        'anon': '20/min',
        'user': '100/min',
        'openai': '5/min',
    },
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 25,
}

SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=60),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': True,
    'AUTH_COOKIE_HTTP_ONLY': True,
    'AUTH_COOKIE_SECURE': not DEBUG,
    'AUTH_COOKIE_SAMESITE': 'Strict',
    'SIGNING_KEY': config('JWT_SECRET', default=SECRET_KEY),
}

# CORS
CORS_ALLOWED_ORIGINS = [origin.strip() for origin in config('FRONTEND_URL', default='').split(',') if origin.strip()]
if not DEBUG and CORS_ALLOWED_ORIGINS == ['*']:
    raise ImproperlyConfigured('CORS_ALLOWED_ORIGINS cannot be wildcard in production')
CORS_ALLOW_CREDENTIALS = True

# Celery
CELERY_BROKER_URL = config('REDIS_URL', default='redis://localhost:6379/0')
CELERY_RESULT_BACKEND = 'django-db'
CELERY_CACHE_BACKEND = 'django-cache'
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = 'UTC'
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_DEFAULT_QUEUE = 'default'
CELERY_TASK_ROUTES = {
    'apps.consultations.tasks.process_consultation': {'queue': 'ai'},
    'apps.consultations.tasks.process_zoom_consultation': {'queue': 'ai'},
}

# OpenAI
OPENAI_API_KEY = config('OPENAI_API_KEY', default='')
TRANSCRIPTION_DAILY_MINUTE_CAP = config('TRANSCRIPTION_DAILY_MINUTE_CAP', default=120, cast=int)

# Zoom configuration (server-to-server OAuth)
ZOOM_OAUTH_CLIENT_ID = config('ZOOM_OAUTH_CLIENT_ID', default='')
ZOOM_OAUTH_CLIENT_SECRET = config('ZOOM_OAUTH_CLIENT_SECRET', default='')
ZOOM_OAUTH_ACCOUNT_ID = config('ZOOM_OAUTH_ACCOUNT_ID', default='')

# Recall.ai configuration
RECALL_AI_API_KEY = config('RECALL_AI_API_KEY', default='')
RECALL_AI_WEBHOOK_SECRET = config('RECALL_AI_WEBHOOK_SECRET', default='')
RECALL_SVIX_WEBHOOK_SECRET = config('RECALL_SVIX_WEBHOOK_SECRET', default='')

# File Storage
USE_S3 = config('USE_S3', default=False, cast=bool)

if USE_S3:
    AWS_ACCESS_KEY_ID = config('AWS_ACCESS_KEY_ID')
    AWS_SECRET_ACCESS_KEY = config('AWS_SECRET_ACCESS_KEY')
    AWS_STORAGE_BUCKET_NAME = config('AWS_STORAGE_BUCKET_NAME')
    AWS_S3_ENDPOINT_URL = config('AWS_S3_ENDPOINT_URL')
    AWS_S3_REGION_NAME = config('AWS_S3_REGION_NAME', default='us-east-1')
    AWS_DEFAULT_ACL = None
    AWS_S3_FILE_OVERWRITE = False
    STORAGES = {
        'default': {'BACKEND': 'storages.backends.s3boto3.S3Boto3Storage'},
        'staticfiles': {'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage'},
    }
else:
    MEDIA_URL = '/media/'
    MEDIA_ROOT = BASE_DIR / 'media'

STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'

# File upload limits
DATA_UPLOAD_MAX_MEMORY_SIZE = 209715200   # 200MB
FILE_UPLOAD_MAX_MEMORY_SIZE = 209715200   # 200MB

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True
