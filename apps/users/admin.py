from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import User
from .models import DoctorProfile


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ['email', 'name', 'is_staff', 'date_joined']
    ordering = ['-date_joined']


@admin.register(DoctorProfile)
class DoctorProfileAdmin(admin.ModelAdmin):
    list_display = ['doctor', 'specialty', 'template_preference', 'onboarding_completed', 'updated_at']
    list_filter = ['template_preference', 'onboarding_completed', 'specialty']
    search_fields = ['doctor__email', 'specialty']
