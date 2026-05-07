from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("diagnosis", "0002_add_doctors_note"),
    ]

    operations = [
        migrations.AddField(
            model_name="consultationreport",
            name="diagnosis_insufficient_information",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="consultationreport",
            name="diagnosis_insufficient_reason",
            field=models.TextField(blank=True, default=""),
        ),
    ]
