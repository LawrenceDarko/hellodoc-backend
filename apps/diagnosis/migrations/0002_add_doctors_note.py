from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("diagnosis", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="consultationreport",
            name="doctors_note",
            field=models.TextField(
                blank=True,
                help_text="Full AI-generated doctor's note in clinical narrative style.",
            ),
        ),
    ]
