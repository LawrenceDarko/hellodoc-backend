import uuid
from django.db import models
from django.conf import settings


class Consultation(models.Model):
    """
    Created immediately when a doctor submits a file upload or schedules a Zoom call.
    The status field tracks the Celery processing pipeline.
    """
    SOURCE_CHOICES = [('zoom', 'Zoom Call'), ('upload', 'Upload')]

    STATUS_CHOICES = [
        ('pending', 'Pending'),           # Just created, file saved, task queued
        ('transcribing', 'Transcribing'), # Celery: Whisper is running
        ('analyzing', 'Analyzing'),       # Celery: GPT-4 generating SOAP/diagnosis
        ('completed', 'Completed'),       # All steps done, report is ready
        ('failed', 'Failed'),             # Something went wrong in the pipeline
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    doctor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='consultations'
    )
    patient = models.ForeignKey(
        'patients.Patient',
        on_delete=models.CASCADE,
        related_name='consultations'
    )
    source = models.CharField(max_length=10, choices=SOURCE_CHOICES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    progress_step = models.CharField(max_length=100, blank=True, default='')
    # For uploads
    audio_file = models.FileField(upload_to='consultations/audio/', null=True, blank=True)
    audio_file_name = models.CharField(max_length=255, blank=True)
    # For Zoom
    zoom_link = models.CharField(max_length=500, null=True, blank=True)
    scheduled_at = models.DateTimeField(null=True, blank=True)
    raw_transcript = models.TextField(
        blank=True,
        default='',
        help_text="Raw Whisper transcription. Used internally for AI analysis. Not shown to users."
    )
    # Metadata
    duration_minutes = models.IntegerField(null=True, blank=True)
    notes = models.TextField(null=True, blank=True)
    error_message = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Consultation: {self.patient.name} — {self.get_status_display()}"
