from django.contrib import admin
from django.contrib import messages
from django import forms
from django.db import models
from django.urls import reverse
from django.utils.html import format_html
from django.core.exceptions import ValidationError
from .models import WireTransfer, TrackingStep, TransferSourceDocument, TransferStatusHistory, TrackerSettings


class WireTransferAdminForm(forms.ModelForm):
    status_update_note = forms.CharField(
        required=False, widget=forms.Textarea(attrs={'rows': 2}),
        help_text='Optional internal note saved with a status history entry.'
    )

    class Meta:
        model = WireTransfer
        fields = '__all__'


class TrackingStepInline(admin.TabularInline):
    model = TrackingStep
    extra = 1
    fields = ('step_order', 'bank_name', 'bank_bic', 'location', 'role', 'status_label', 'status_code', 'fee_deducted', 'timestamp')


class SourceDocumentInline(admin.TabularInline):
    model = TransferSourceDocument
    extra = 1
    fields = ('file', 'description', 'download_link', 'uploaded_by', 'uploaded_at')
    readonly_fields = ('download_link', 'uploaded_by', 'uploaded_at')
    formfield_overrides = {models.FileField: {'widget': forms.FileInput}}

    @admin.display(description='Private download')
    def download_link(self, obj):
        if not obj.pk:
            return '—'
        url = reverse('tracker:download_source_document', args=[obj.pk])
        return format_html('<a href="{}">Download source file</a>', url)


class StatusHistoryInline(admin.TabularInline):
    model = TransferStatusHistory
    extra = 0
    can_delete = False
    fields = ('previous_status', 'status', 'status_reason', 'status_observed_at', 'note', 'changed_by', 'changed_at')
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(WireTransfer)
class WireTransferAdmin(admin.ModelAdmin):
    form = WireTransferAdminForm
    list_display = ('uetr', 'reference_number', 'currency', 'amount', 'status', 'status_observed_at', 'is_published', 'updated_at')
    list_filter = ('is_published', 'status', 'source_type', 'currency', 'charge_type')
    search_fields = ('uetr', 'reference_number', 'sender_name', 'beneficiary_name')
    inlines = [SourceDocumentInline, TrackingStepInline, StatusHistoryInline]
    readonly_fields = ('created_at', 'updated_at')
    actions = ['publish_records', 'unpublish_records']
    fieldsets = (
        ('Search identifiers', {'fields': ('uetr', 'reference_number')}),
        ('Payment', {'fields': ('date_of_payment', 'amount', 'currency', 'charge_type')}),
        ('Recorded status', {'fields': ('status', 'status_reason', 'status_observed_at', 'eta_delivery', 'status_update_note')}),
        ('Information source', {'fields': ('source_type', 'source_description')}),
        ('Parties and banks', {'fields': (
            'sender_name', 'sender_account', 'sender_bank_name', 'sender_bank_bic',
            'beneficiary_name', 'beneficiary_account', 'beneficiary_bank_name', 'beneficiary_bank_bic',
        )}),
        ('Publication', {'fields': ('is_published', 'created_at', 'updated_at')}),
    )

    def save_model(self, request, obj, form, change):
        previous = None
        if change:
            previous = WireTransfer.objects.filter(pk=obj.pk).values(
                'status', 'status_reason', 'status_observed_at'
            ).first()
        super().save_model(request, obj, form, change)
        note = form.cleaned_data.get('status_update_note', '')
        if previous is None or note or any(previous[key] != getattr(obj, key) for key in (
            'status', 'status_reason', 'status_observed_at'
        )):
            TransferStatusHistory.objects.create(
                transfer=obj,
                previous_status=previous['status'] if previous else '',
                status=obj.status,
                status_reason=obj.status_reason,
                status_observed_at=obj.status_observed_at,
                note=note,
                changed_by=request.user,
            )

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        form.instance.source_documents.filter(uploaded_by__isnull=True).update(uploaded_by=request.user)

    @admin.action(description="Publish selected records for customer search")
    def publish_records(self, request, queryset):
        published = 0
        rejected = 0
        for record in queryset:
            record.is_published = True
            try:
                record.full_clean()
            except ValidationError:
                rejected += 1
                continue
            record.save(update_fields=['is_published', 'updated_at'])
            published += 1
        if published:
            self.message_user(request, f'{published} record(s) published.', messages.SUCCESS)
        if rejected:
            self.message_user(request, f'{rejected} record(s) need a source and observed status time before publishing.', messages.WARNING)

    @admin.action(description="Remove selected records from customer search")
    def unpublish_records(self, request, queryset):
        for record in queryset:
            record.is_published = False
            record.save(update_fields=['is_published', 'updated_at'])


@admin.register(TransferSourceDocument)
class TransferSourceDocumentAdmin(admin.ModelAdmin):
    list_display = ('original_filename', 'transfer', 'description', 'download_link', 'uploaded_at', 'uploaded_by')
    list_filter = ('uploaded_at',)
    search_fields = ('original_filename', 'description', 'transfer__uetr', 'transfer__reference_number')
    readonly_fields = ('uploaded_at', 'download_link')

    @admin.display(description='Download File')
    def download_link(self, obj):
        if not obj.pk or not obj.file:
            return '—'
        url = reverse('tracker:download_source_document', args=[obj.pk])
        return format_html('<a href="{}" target="_blank">Download source file</a>', url)


@admin.register(TransferStatusHistory)
class TransferStatusHistoryAdmin(admin.ModelAdmin):
    list_display = ('transfer', 'status', 'previous_status', 'status_observed_at', 'changed_at', 'changed_by')
    list_filter = ('status', 'previous_status', 'changed_at')
    search_fields = ('transfer__uetr', 'transfer__reference_number', 'status_reason', 'note')
    readonly_fields = ('changed_at',)


@admin.register(TrackingStep)
class TrackingStepAdmin(admin.ModelAdmin):
    list_display = ('transfer', 'step_order', 'bank_name', 'bank_bic', 'role', 'status_label', 'fee_deducted')
    list_filter = ('status_code', 'role')
    search_fields = ('bank_name', 'bank_bic', 'transfer__uetr')


@admin.register(TrackerSettings)
class TrackerSettingsAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'require_login', 'updated_at', 'updated_by')
    list_editable = ('require_login',)
    readonly_fields = ('updated_at', 'updated_by')
    actions = ['enable_login_requirement', 'disable_login_requirement']

    fieldsets = (
        ('Wire Tracker Access Configuration', {
            'fields': ('require_login',),
            'description': (
                'Configure whether users must be registered and logged in to use the Wire Tracker. '
                'By default, this is disabled (public access without login). When enabled, any visitor '
                'attempting to search or track a wire transfer will be prompted to log in or register.'
            ),
        }),
        ('Audit Log', {
            'fields': ('updated_at', 'updated_by'),
            'classes': ('collapse',),
        }),
    )

    def has_add_permission(self, request):
        return not TrackerSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        TrackerSettings.get_settings()
        return super().changelist_view(request, extra_context=extra_context)

    def save_model(self, request, obj, form, change):
        obj.updated_by = request.user
        super().save_model(request, obj, form, change)

    @admin.action(description="Require login to use Wire Tracker")
    def enable_login_requirement(self, request, queryset):
        for item in queryset:
            item.require_login = True
            item.updated_by = request.user
            item.save()
        self.message_user(request, "Wire Tracker now requires users to be logged in / registered.", messages.SUCCESS)

    @admin.action(description="Disable login requirement (Public access without login)")
    def disable_login_requirement(self, request, queryset):
        for item in queryset:
            item.require_login = False
            item.updated_by = request.user
            item.save()
        self.message_user(request, "Wire Tracker is now open to the public without login requirement.", messages.SUCCESS)
