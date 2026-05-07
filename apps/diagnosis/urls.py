from django.urls import path
from . import views

urlpatterns = [
    path('<uuid:consultation_id>/report/', views.consultation_report, name='consultation-report'),
    path('<uuid:consultation_id>/export/', views.export_report, name='consultation-export'),
]
