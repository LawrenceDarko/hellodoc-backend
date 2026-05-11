import uuid
from django.db import models
from django.conf import settings
from apps.core.models import SoftDeleteModel


class Patient(SoftDeleteModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    doctor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='patients'
    )
    name = models.CharField(max_length=255)
    email = models.EmailField()
    date_of_birth = models.DateField(null=True, blank=True)
    phone = models.CharField(max_length=20, null=True, blank=True)
    notes = models.TextField(null=True, blank=True)
    # Clinical snapshot stored as JSON: { active_problems: [], medications: [], alerts: [] }
    clinical_snapshot = models.JSONField(null=True, blank=True, default=dict)
    # Care plan stored as JSON: { next_steps: str, follow_up: str }
    care_plan = models.JSONField(null=True, blank=True, default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} — Dr. {self.doctor.email}"
