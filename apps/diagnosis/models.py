from django.db import models
from apps.core.models import SoftDeleteModel


class ConsultationReport(SoftDeleteModel):
    consultation = models.OneToOneField(
        'consultations.Consultation',
        on_delete=models.CASCADE,
        related_name='report'
    )
    # Primary output — detailed narrative doctor's note
    doctors_note = models.TextField(
        blank=True,
        help_text="Full AI-generated doctor's note in clinical narrative style."
    )
    # SOAP breakdown derived from the doctor's note
    soap_subjective = models.TextField(blank=True)
    soap_objective = models.TextField(blank=True)
    soap_assessment = models.TextField(blank=True)
    soap_plan = models.TextField(blank=True)
    diagnosis_insufficient_information = models.BooleanField(default=False)
    diagnosis_insufficient_reason = models.TextField(blank=True, default='')

    generated_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Report — {self.consultation}"


class DiagnosisItem(SoftDeleteModel):
    """
    Individual condition in the differential diagnosis.
    Ranked by likelihood descending.
    """
    report = models.ForeignKey(
        ConsultationReport,
        on_delete=models.CASCADE,
        related_name='diagnosis_items'
    )
    condition = models.CharField(max_length=255)
    likelihood = models.FloatField(help_text="Percentage likelihood 0-100")
    icd_code = models.CharField(max_length=20)
    reasoning = models.TextField(blank=True)

    class Meta:
        ordering = ['-likelihood']

    def __str__(self):
        return f"{self.condition} ({self.likelihood}%)"


class ScanRecommendation(SoftDeleteModel):
    """
    Imaging or lab test recommended based on the diagnosis.
    """
    PRIORITY_CHOICES = [('urgent', 'Urgent'), ('routine', 'Routine')]

    report = models.ForeignKey(
        ConsultationReport,
        on_delete=models.CASCADE,
        related_name='scan_recommendations'
    )
    scan_name = models.CharField(max_length=255)
    reason = models.TextField()
    priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES)

    class Meta:
        ordering = ['priority']

    def __str__(self):
        return f"{self.scan_name} [{self.priority}]"
