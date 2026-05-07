from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("consultations", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="ConsultationReport",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("soap_subjective", models.TextField(blank=True)),
                ("soap_objective", models.TextField(blank=True)),
                ("soap_assessment", models.TextField(blank=True)),
                ("soap_plan", models.TextField(blank=True)),
                ("generated_at", models.DateTimeField(auto_now_add=True)),
                (
                    "consultation",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="report",
                        to="consultations.consultation",
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="DiagnosisItem",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("condition", models.CharField(max_length=255)),
                (
                    "likelihood",
                    models.FloatField(help_text="Percentage likelihood 0-100"),
                ),
                ("icd_code", models.CharField(max_length=20)),
                ("reasoning", models.TextField(blank=True)),
                (
                    "report",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="diagnosis_items",
                        to="diagnosis.consultationreport",
                    ),
                ),
            ],
            options={
                "ordering": ["-likelihood"],
            },
        ),
        migrations.CreateModel(
            name="ScanRecommendation",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("scan_name", models.CharField(max_length=255)),
                ("reason", models.TextField()),
                (
                    "priority",
                    models.CharField(
                        choices=[("urgent", "Urgent"), ("routine", "Routine")],
                        max_length=10,
                    ),
                ),
                (
                    "report",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="scan_recommendations",
                        to="diagnosis.consultationreport",
                    ),
                ),
            ],
            options={
                "ordering": ["priority"],
            },
        ),
    ]

