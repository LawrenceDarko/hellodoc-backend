from django.urls import path
from . import views

urlpatterns = [
    path('', views.patient_list, name='patient-list'),
    path('<uuid:patient_id>/', views.patient_detail, name='patient-detail'),
]
