from django.contrib import admin
from .models import ConsultationReport, DiagnosisItem, ScanRecommendation


class DiagnosisItemInline(admin.TabularInline):
    model = DiagnosisItem
    extra = 0


class ScanRecommendationInline(admin.TabularInline):
    model = ScanRecommendation
    extra = 0


@admin.register(ConsultationReport)
class ConsultationReportAdmin(admin.ModelAdmin):
    list_display = ['consultation', 'generated_at']
    inlines = [DiagnosisItemInline, ScanRecommendationInline]
