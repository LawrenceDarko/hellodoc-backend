from django.urls import path
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from . import views

urlpatterns = [
    path('login/', TokenObtainPairView.as_view(), name='auth-login'),
    path('register/', views.register, name='auth-register'),
    path('refresh/', TokenRefreshView.as_view(), name='auth-refresh'),
    path('logout/', views.logout, name='auth-logout'),
    path('me/', views.me, name='auth-me'),
]
