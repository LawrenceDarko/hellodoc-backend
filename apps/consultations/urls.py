from django.urls import path
from . import views

urlpatterns = [
    path('', views.consultation_list, name='consultation-list'),
    path('upload/', views.upload_consultation, name='consultation-upload'),
    path('schedule/', views.schedule_consultation, name='consultation-schedule'),
    path('<uuid:consultation_id>/', views.consultation_detail, name='consultation-detail'),
    path('<uuid:consultation_id>/status/', views.consultation_status, name='consultation-status'),
]
