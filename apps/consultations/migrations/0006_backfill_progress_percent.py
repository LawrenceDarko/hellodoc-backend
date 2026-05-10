from django.db import migrations


def backfill_progress_percent(apps, schema_editor):
    Consultation = apps.get_model('consultations', 'Consultation')
    Consultation.objects.filter(status='completed').update(progress_percent=100)
    Consultation.objects.filter(status='failed').update(progress_percent=100)
    Consultation.objects.filter(status='analyzing', progress_percent=0).update(progress_percent=60)
    Consultation.objects.filter(status='transcribing', progress_percent=0).update(progress_percent=20)
    Consultation.objects.filter(status='processing', progress_percent=0).update(progress_percent=8)
    Consultation.objects.filter(status='in_progress', progress_percent=0).update(progress_percent=5)
    Consultation.objects.filter(status='pending', progress_percent=0).update(progress_percent=5)


class Migration(migrations.Migration):

    dependencies = [
        ('consultations', '0005_consultation_progress_percent'),
    ]

    operations = [
        migrations.RunPython(backfill_progress_percent, migrations.RunPython.noop),
    ]
