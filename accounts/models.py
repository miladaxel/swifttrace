from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator, MinValueValidator, URLValidator
from django.db import models
from django.db.models import Q
from decimal import Decimal
from pathlib import Path
import uuid

from tracker.storage import private_document_storage


def purchase_receipt_path(instance, filename):
    return f'plan_receipts/{instance.pk}/{uuid.uuid4().hex}{Path(filename).suffix.lower()}'


def validate_receipt_size(value):
    if value.size > 5 * 1024 * 1024:
        raise ValidationError('Receipt images must be 5 MB or smaller.')


class MembershipTier(models.Model):
    FREE = 'free'
    SILVER = 'silver'
    GOLD = 'gold'
    LEVELS = [(FREE, 'Free'), (SILVER, 'Silver'), (GOLD, 'Gold')]

    level = models.CharField(max_length=10, choices=LEVELS, primary_key=True)
    monthly_search_limit = models.PositiveIntegerField(default=0)
    monthly_download_limit = models.PositiveIntegerField(default=0)
    monthly_price_usdt = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        validators=[MinValueValidator(Decimal('0.00'))],
        verbose_name='Monthly price (USDT)',
        help_text='Set a price for Silver or Gold. Leave blank until a price is decided.',
    )
    payment_url = models.URLField(
        max_length=500, blank=True, validators=[URLValidator(schemes=['https'])],
        verbose_name='Payment link',
        help_text='HTTPS link encoded in the QR code and shown to customers.',
    )
    payment_network = models.CharField(
        max_length=50, blank=True, verbose_name='USDT network',
        help_text='Name the network customers must use, for example TRC20.',
    )

    class Meta:
        ordering = ['level']
        verbose_name = 'Membership tier'

    def __str__(self):
        return self.get_level_display()

    @property
    def is_demo_payment(self):
        return self.payment_url == f'https://example.com/?swifttrace-demo={self.level}'

    def clean(self):
        super().clean()
        if self.level == self.FREE and self.monthly_price_usdt not in (None, Decimal('0.00')):
            raise ValidationError({'monthly_price_usdt': 'Free must have no price.'})
        if self.level in (self.SILVER, self.GOLD) and self.monthly_price_usdt is not None and self.monthly_price_usdt <= 0:
            raise ValidationError({'monthly_price_usdt': 'Set a positive USDT price or leave it blank.'})


class UserMembership(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='membership')
    tier = models.ForeignKey(MembershipTier, on_delete=models.PROTECT, default=MembershipTier.FREE)
    expires_at = models.DateTimeField(null=True, blank=True, db_index=True)
    monthly_search_limit = models.PositiveIntegerField(null=True, blank=True)
    monthly_download_limit = models.PositiveIntegerField(null=True, blank=True)

    def __str__(self):
        return f'{self.user}: {self.tier}'

    def capture_limits(self, tier):
        self.monthly_search_limit = tier.monthly_search_limit
        self.monthly_download_limit = tier.monthly_download_limit

    def clear_limits(self):
        self.monthly_search_limit = None
        self.monthly_download_limit = None


class PlanPurchase(models.Model):
    AWAITING_PAYMENT = 'awaiting_payment'
    SUBMITTED = 'submitted'
    APPROVED = 'approved'
    REJECTED = 'rejected'
    STATUS_CHOICES = [
        (AWAITING_PAYMENT, 'Awaiting payment'),
        (SUBMITTED, 'Submitted for review'),
        (APPROVED, 'Approved'),
        (REJECTED, 'Rejected'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='plan_purchases')
    tier = models.ForeignKey(MembershipTier, on_delete=models.PROTECT, related_name='purchases')
    price_usdt = models.DecimalField(max_digits=10, decimal_places=2)
    monthly_search_limit = models.PositiveIntegerField(null=True, blank=True)
    monthly_download_limit = models.PositiveIntegerField(null=True, blank=True)
    payment_url = models.URLField(max_length=500)
    payment_network = models.CharField(max_length=50)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=AWAITING_PAYMENT)
    txid = models.CharField(max_length=255, unique=True, null=True, blank=True, verbose_name='Transaction ID')
    receipt_image = models.ImageField(
        storage=private_document_storage, upload_to=purchase_receipt_path,
        null=True, blank=True,
        validators=[FileExtensionValidator(['jpg', 'jpeg', 'png', 'webp']), validate_receipt_size],
    )
    created_at = models.DateTimeField(auto_now_add=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='reviewed_plan_purchases',
    )
    review_note = models.TextField(blank=True)
    access_expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'tier'], condition=Q(status='awaiting_payment'),
                name='one_open_purchase_per_tier',
            ),
        ]

    def __str__(self):
        return f'{self.user} - {self.tier} ({self.get_status_display()})'

    @property
    def is_demo_payment(self):
        return self.payment_url == f'https://example.com/?swifttrace-demo={self.tier_id}'


class LoginRateWindow(models.Model):
    lookup_key = models.CharField(max_length=64)
    window_start = models.DateTimeField()
    attempts = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['lookup_key', 'window_start'], name='unique_login_rate_window')]
        indexes = [models.Index(fields=['window_start'], name='login_rate_window_idx')]


class MonthlyUsage(models.Model):
    identity = models.CharField(max_length=80)
    month = models.DateField()
    searches = models.PositiveIntegerField(default=0)
    downloads = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['identity', 'month'], name='unique_membership_month')]
