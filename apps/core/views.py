from django.conf import settings
from django.db import connection
from redis import Redis
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response


@api_view(['GET'])
@permission_classes([AllowAny])
def health(request):
    checks = {'status': 'ok', 'db': 'ok', 'redis': 'ok'}

    try:
        connection.ensure_connection()
    except Exception as exc:
        checks.update({'status': 'error', 'db': str(exc)})

    try:
        Redis.from_url(settings.CELERY_BROKER_URL, socket_connect_timeout=2).ping()
    except Exception as exc:
        checks.update({'status': 'error', 'redis': str(exc)})

    response_status = status.HTTP_200_OK if checks['status'] == 'ok' else status.HTTP_503_SERVICE_UNAVAILABLE
    return Response(checks, status=response_status)
