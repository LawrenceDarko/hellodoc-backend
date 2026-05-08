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
        ('pending', 'Pending'),
        ('scheduled', 'Scheduled'),       # Zoom meeting created, bot scheduled to join
        ('in_progress', 'In Progress'),   # Recall.ai bot has joined the call and is recording
        ('processing', 'Processing'),     # Call ended, downloading recording from Recall.ai
        ('transcribing', 'Transcribing'),
        ('analyzing', 'Analyzing'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
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
    # Zoom meeting details
    zoom_meeting_id = models.CharField(max_length=100, blank=True, default='')
    zoom_join_url = models.CharField(max_length=1000, blank=True, default='')
    zoom_start_url = models.CharField(max_length=1000, blank=True, default='')
    zoom_password = models.CharField(max_length=50, blank=True, default='')
    # Recall.ai bot — used to match incoming webhooks back to this consultation
    recall_bot_id = models.CharField(
        max_length=255,
        blank=True,
        default='',
        help_text="Recall.ai bot UUID. Set after bot is created. Used to match webhooks."
    )
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
