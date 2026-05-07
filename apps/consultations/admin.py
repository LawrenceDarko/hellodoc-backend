from django.contrib import admin
from .models import Consultation


@admin.register(Consultation)
class ConsultationAdmin(admin.ModelAdmin):
    list_display = ['patient', 'doctor', 'source', 'status', 'progress_step', 'created_at']
    list_filter = ['status', 'source']
    search_fields = ['patient__name', 'doctor__email']
    readonly_fields = ['id', 'status', 'progress_step', 'error_message', 'created_at', 'updated_at']
