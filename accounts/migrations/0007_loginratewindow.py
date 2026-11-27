from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0006_freeze_plan_limits'),
    ]

    operations = [
        migrations.CreateModel(
            name='LoginRateWindow',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('lookup_key', models.CharField(max_length=64)),
                ('window_start', models.DateTimeField()),
                ('attempts', models.PositiveIntegerField(default=0)),
            ],
            options={
                'indexes': [models.Index(fields=['window_start'], name='login_rate_window_idx')],
            },
        ),
        migrations.AddConstraint(
            model_name='loginratewindow',
            constraint=models.UniqueConstraint(fields=('lookup_key', 'window_start'), name='unique_login_rate_window'),
        ),
    ]
