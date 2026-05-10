from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('consultations', '0004_consultation_deleted_at'),
    ]

    operations = [
        migrations.AddField(
            model_name='consultation',
            name='progress_percent',
            field=models.PositiveSmallIntegerField(default=0),
        ),
    ]
