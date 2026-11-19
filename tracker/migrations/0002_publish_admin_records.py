from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('tracker', '0001_initial')]

    operations = [
        migrations.AddField(
            model_name='wiretransfer',
            name='is_published',
            field=models.BooleanField(default=False, help_text='Only published records can be found by public search.'),
        ),
        migrations.AlterField(
            model_name='wiretransfer',
            name='uetr',
            field=models.CharField(blank=True, db_index=True, help_text='Unique End-to-End Transaction Reference (36-character UUID format)', max_length=64, null=True, unique=True),
        ),
    ]
