from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("consultations", "0001_initial"),
    ]

    operations = [
        migrations.DeleteModel(
            name="TranscriptEntry",
        ),
        migrations.AddField(
            model_name="consultation",
            name="raw_transcript",
            field=models.TextField(
                blank=True,
                default="",
                help_text="Raw Whisper transcription. Used internally for AI analysis. Not shown to users.",
            ),
        ),
    ]
