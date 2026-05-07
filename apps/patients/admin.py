from django.contrib import admin
from .models import Patient


@admin.register(Patient)
class PatientAdmin(admin.ModelAdmin):
    list_display = ['name', 'email', 'doctor', 'created_at']
    search_fields = ['name', 'email']
    list_filter = ['doctor']
