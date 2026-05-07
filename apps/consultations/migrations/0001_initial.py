import uuid

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("patients", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="Consultation",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                (
                    "source",
                    models.CharField(
                        choices=[("zoom", "Zoom Call"), ("upload", "Upload")],
                        max_length=10,
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("transcribing", "Transcribing"),
                            ("analyzing", "Analyzing"),
                            ("completed", "Completed"),
                            ("failed", "Failed"),
                        ],
                        default="pending",
                        max_length=20,
                    ),
                ),
                ("progress_step", models.CharField(blank=True, default="", max_length=100)),
                (
                    "audio_file",
                    models.FileField(blank=True, null=True, upload_to="consultations/audio/"),
                ),
                ("audio_file_name", models.CharField(blank=True, max_length=255)),
                ("zoom_link", models.CharField(blank=True, max_length=500, null=True)),
                ("scheduled_at", models.DateTimeField(blank=True, null=True)),
                ("duration_minutes", models.IntegerField(blank=True, null=True)),
                ("notes", models.TextField(blank=True, null=True)),
                ("error_message", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "doctor",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="consultations",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "patient",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="consultations",
                        to="patients.patient",
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
        migrations.CreateModel(
            name="TranscriptEntry",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("order", models.PositiveIntegerField()),
                ("timestamp", models.CharField(max_length=20)),
                (
                    "speaker",
                    models.CharField(
                        choices=[("Doctor", "Doctor"), ("Patient", "Patient")],
                        max_length=10,
                    ),
                ),
                ("text", models.TextField()),
                (
                    "consultation",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="transcript_entries",
                        to="consultations.consultation",
                    ),
                ),
            ],
            options={
                "ordering": ["order"],
            },
        ),
    ]
