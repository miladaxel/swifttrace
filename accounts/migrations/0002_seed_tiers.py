from django.db import migrations
from django.conf import settings


def seed_tiers(apps, schema_editor):
    Tier = apps.get_model('accounts', 'MembershipTier')
    for level, searches, downloads in (
        ('free', 10, 3),
        ('silver', 100, 30),
        ('gold', 1000, 300),
    ):
        Tier.objects.get_or_create(
            level=level,
            defaults={'monthly_search_limit': searches, 'monthly_download_limit': downloads},
        )
    User = apps.get_model(*settings.AUTH_USER_MODEL.split('.'))
    Membership = apps.get_model('accounts', 'UserMembership')
    for user_id in User.objects.values_list('pk', flat=True).iterator():
        Membership.objects.get_or_create(user_id=user_id, defaults={'tier_id': 'free'})


class Migration(migrations.Migration):
    dependencies = [('accounts', '0001_initial')]
    operations = [migrations.RunPython(seed_tiers, migrations.RunPython.noop)]
