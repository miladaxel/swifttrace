import uuid
from pathlib import Path
from django.db import models
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from django.conf import settings
from .storage import private_document_storage


def source_document_path(instance, filename):
    return f'wire_transfers/{instance.transfer_id}/{uuid.uuid4().hex}{Path(filename).suffix.lower()}'


def validate_source_document_size(value):
    if value.size > 5 * 1024 * 1024:
        raise ValidationError('Source documents must be 5 MB or smaller.')


class WireTransfer(models.Model):
    SOURCE_CHOICES = [
        ('MT103', 'MT103 confirmation'),
        ('PACS008', 'pacs.008 message'),
        ('BANK', 'Bank confirmation'),
        ('OTHER', 'Other documented source'),
    ]

    STATUS_CHOICES = [
        ('ACSP', 'Accepted Settlement In Process'),
        ('ACCC', 'Settlement Completed / Credited'),
        ('RJCT', 'Rejected / Returned'),
        ('HOLD', 'Held / Compliance Review'),
        ('PDNG', 'Pending Initiation'),
    ]

    CHARGE_CHOICES = [
        ('SHA', 'Shared (SHA)'),
        ('OUR', 'Sender Pays All (OUR)'),
        ('BEN', 'Beneficiary Pays All (BEN)'),
    ]

    uetr = models.CharField(
        max_length=64,
        unique=True,
        db_index=True,
        blank=True,
        null=True,
        help_text="Unique End-to-End Transaction Reference (36-character UUID format)"
    )
    reference_number = models.CharField(
        max_length=64,
        blank=True,
        db_index=True,
        help_text="Sender's Reference / MT103 Field :20:"
    )
    date_of_payment = models.DateField(
        help_text="Date when wire transfer was initiated"
    )
    amount = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        help_text="Transfer amount"
    )
    currency = models.CharField(
        max_length=3,
        help_text="3-letter ISO Currency Code (e.g. USD, EUR, GBP, AED)"
    )
    
    # Parties
    sender_name = models.CharField(max_length=255, blank=True)
    sender_account = models.CharField(max_length=64, blank=True)
    sender_bank_name = models.CharField(max_length=255, blank=True)
    sender_bank_bic = models.CharField(max_length=11, blank=True)
    
    beneficiary_name = models.CharField(max_length=255, blank=True)
    beneficiary_account = models.CharField(max_length=64, blank=True)
    beneficiary_bank_name = models.CharField(max_length=255, blank=True)
    beneficiary_bank_bic = models.CharField(max_length=11, blank=True)

    charge_type = models.CharField(
        max_length=3,
        choices=CHARGE_CHOICES,
        default='SHA'
    )
    status = models.CharField(
        max_length=10,
        choices=STATUS_CHOICES,
        default='PDNG'
    )
    status_reason = models.TextField(
        blank=True,
        help_text="Detailed status explanation or delay cause"
    )
    source_type = models.CharField(
        max_length=10, choices=SOURCE_CHOICES, blank=True,
        help_text='Select the document or source used to enter this payment information.'
    )
    source_description = models.CharField(
        max_length=255, blank=True,
        help_text='Identify the institution, document reference, or other origin of the information.'
    )
    status_observed_at = models.DateTimeField(
        null=True, blank=True,
        help_text='When this status was observed in the source, not when the record was edited.'
    )
    is_published = models.BooleanField(
        default=False,
        help_text="Only published records can be found by public search."
    )
    eta_delivery = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Estimated Time of Arrival"
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-date_of_payment', '-created_at']
        verbose_name = "Wire Transfer"
        verbose_name_plural = "Wire Transfers"

    def __str__(self):
        return f"{self.currency} {self.amount:,.2f} - {self.uetr or self.reference_number}"

    def clean(self):
        if self.uetr:
            try:
                self.uetr = str(uuid.UUID(self.uetr.strip()))
            except (ValueError, AttributeError):
                raise ValidationError({'uetr': 'Enter a valid 36-character UETR.'})
        else:
            self.uetr = None
        self.reference_number = (self.reference_number or '').strip()
        self.currency = (self.currency or '').strip().upper()
        if not self.uetr and not self.reference_number:
            raise ValidationError("Enter a UETR or a payment reference.")
        if self.amount is not None and self.amount <= 0:
            raise ValidationError({'amount': 'Amount must be greater than zero.'})
        if len(self.currency) != 3 or not self.currency.isalpha():
            raise ValidationError({'currency': 'Enter a three-letter currency code.'})
        if self.is_published:
            errors = {}
            if not self.source_type:
                errors['source_type'] = 'Select a source before publishing.'
            if not (self.source_description or '').strip():
                errors['source_description'] = 'Describe the source before publishing.'
            if not self.status_observed_at:
                errors['status_observed_at'] = 'Enter when the reported status was observed.'
            if errors:
                raise ValidationError(errors)

    @property
    def total_deducted_fees(self):
        return sum(step.fee_deducted for step in self.steps.all())

    @staticmethod
    def mask_account(value):
        characters = ''.join(character for character in (value or '') if character.isalnum())
        return f'••••{characters[-4:]}' if len(characters) > 4 else '••••'

    @property
    def masked_sender_account(self):
        return self.mask_account(self.sender_account)

    @property
    def masked_beneficiary_account(self):
        return self.mask_account(self.beneficiary_account)


class TrackingStep(models.Model):
    transfer = models.ForeignKey(
        WireTransfer,
        related_name='steps',
        on_delete=models.CASCADE
    )
    step_order = models.PositiveIntegerField(default=1)
    bank_name = models.CharField(max_length=255)
    bank_bic = models.CharField(max_length=11)
    location = models.CharField(max_length=120, help_text="e.g. New York, US")
    role = models.CharField(
        max_length=64,
        help_text="e.g. Ordering Institution, Intermediary Bank, Beneficiary Bank"
    )
    status_label = models.CharField(max_length=64, default="Completed")
    status_code = models.CharField(max_length=10, default="ACSP")
    timestamp = models.DateTimeField()
    fee_deducted = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    details = models.TextField(blank=True)

    class Meta:
        ordering = ['step_order']
        verbose_name = "Tracking Step"
        verbose_name_plural = "Tracking Steps"

    def __str__(self):
        return f"Step {self.step_order}: {self.bank_name} ({self.status_label})"


class TransferSourceDocument(models.Model):
    transfer = models.ForeignKey(WireTransfer, related_name='source_documents', on_delete=models.CASCADE)
    file = models.FileField(
        storage=private_document_storage,
        upload_to=source_document_path,
        validators=[
            FileExtensionValidator(['pdf', 'jpg', 'jpeg', 'png', 'heic', 'txt', 'xml']),
            validate_source_document_size,
        ],
    )
    original_filename = models.CharField(max_length=255, blank=True)
    description = models.CharField(max_length=255, blank=True)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-uploaded_at']
        verbose_name = 'Source document'
        verbose_name_plural = 'Source documents'

    def save(self, *args, **kwargs):
        if self.file and not self.original_filename:
            self.original_filename = Path(self.file.name).name
        super().save(*args, **kwargs)

    def __str__(self):
        return self.original_filename or f'Source document {self.pk}'


class TransferStatusHistory(models.Model):
    transfer = models.ForeignKey(WireTransfer, related_name='status_history', on_delete=models.CASCADE)
    previous_status = models.CharField(max_length=10, blank=True, choices=WireTransfer.STATUS_CHOICES)
    status = models.CharField(max_length=10, choices=WireTransfer.STATUS_CHOICES)
    status_reason = models.TextField(blank=True)
    status_observed_at = models.DateTimeField(null=True, blank=True)
    note = models.TextField(blank=True, help_text='Internal note about this update.')
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    changed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-changed_at', '-pk']
        verbose_name = 'Status history entry'
        verbose_name_plural = 'Status history'

    def __str__(self):
        return f'{self.transfer_id}: {self.previous_status or "New"} → {self.status}'


class SearchRateWindow(models.Model):
    lookup_key = models.CharField(max_length=64)
    window_start = models.DateTimeField()
    attempts = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['lookup_key', 'window_start'], name='unique_wire_search_window')]
        indexes = [models.Index(fields=['window_start'], name='wire_search_window_idx')]


class AccountSearchAttempt(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    created_at = models.DateTimeField(db_index=True)

    class Meta:
        indexes = [models.Index(fields=['user', 'created_at'], name='acct_search_user_time_idx')]


class ResultViewWindow(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    transfer = models.ForeignKey(WireTransfer, on_delete=models.CASCADE)
    expires_at = models.DateTimeField(db_index=True)
    views = models.PositiveIntegerField(default=0)


class TrackerSettings(models.Model):
    require_login = models.BooleanField(
        default=False,
        verbose_name="Require login to use Wire Tracker",
        help_text="If enabled, users must register and log in to search or track wire transfers. If disabled (default), anyone can search and track wires without an account."
    )
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='tracker_settings_updates',
        verbose_name="Last updated by"
    )

    class Meta:
        verbose_name = "Wire Tracker Setting"
        verbose_name_plural = "Wire Tracker Settings"

    def __str__(self):
        status = "Required" if self.require_login else "Not Required (Public)"
        return f"Wire Tracker Login Requirement: {status}"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        pass  # Prevent deleting singleton

    @classmethod
    def get_settings(cls):
        obj, _ = cls.objects.get_or_create(
            pk=1,
            defaults={'require_login': False}
        )
        return obj

    @classmethod
    def is_login_required(cls):
        return cls.get_settings().require_login
