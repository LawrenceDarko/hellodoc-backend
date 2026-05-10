from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from apps.consultations.views import recall_webhook
from apps.core.views import health

urlpatterns = [
    path('health/', health, name='health'),
    path('admin/', admin.site.urls),
    path('api/webhooks/recall/', recall_webhook, name='recall-webhook'),
    path('api/auth/', include('apps.users.urls')),
    path('api/patients/', include('apps.patients.urls')),
    path('api/consultations/', include('apps.consultations.urls')),
    path('api/consultations/', include('apps.diagnosis.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
