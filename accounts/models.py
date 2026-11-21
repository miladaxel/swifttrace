from django.conf import settings
from django.db import models


class MembershipTier(models.Model):
    FREE = 'free'
    SILVER = 'silver'
    GOLD = 'gold'
    LEVELS = [(FREE, 'Free'), (SILVER, 'Silver'), (GOLD, 'Gold')]

    level = models.CharField(max_length=10, choices=LEVELS, primary_key=True)
    monthly_search_limit = models.PositiveIntegerField(default=0)
    monthly_download_limit = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['level']
        verbose_name = 'Membership tier'

    def __str__(self):
        return self.get_level_display()


class UserMembership(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='membership')
    tier = models.ForeignKey(MembershipTier, on_delete=models.PROTECT, default=MembershipTier.FREE)

    def __str__(self):
        return f'{self.user}: {self.tier}'


class MonthlyUsage(models.Model):
    identity = models.CharField(max_length=80)
    month = models.DateField()
    searches = models.PositiveIntegerField(default=0)
    downloads = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['identity', 'month'], name='unique_membership_month')]
