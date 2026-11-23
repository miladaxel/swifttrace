from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin
from django.urls import reverse
from django.utils.html import format_html

from .models import MembershipTier, MonthlyUsage, PlanPurchase, UserMembership


User = get_user_model()
admin.site.unregister(User)


@admin.register(User)
class SuperuserOnlyUserAdmin(UserAdmin):
    """Keep Django's user administration behind the same superuser boundary."""

    def has_module_permission(self, request):
        return request.user.is_active and request.user.is_staff and request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser and super().has_view_permission(request, obj)

    def has_add_permission(self, request):
        return request.user.is_superuser and super().has_add_permission(request)

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser and super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser and super().has_delete_permission(request, obj)


@admin.register(MembershipTier)
class MembershipTierAdmin(admin.ModelAdmin):
    list_display = ('level', 'monthly_search_limit', 'monthly_download_limit', 'monthly_price_usdt', 'payment_network')
    fields = ('level', 'monthly_search_limit', 'monthly_download_limit', 'monthly_price_usdt', 'payment_url', 'payment_network')

    def get_readonly_fields(self, request, obj=None):
        if obj and obj.level == MembershipTier.FREE:
            return ('level', 'monthly_price_usdt', 'payment_url', 'payment_network')
        return ('level',) if obj else ()

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(UserMembership)
class UserMembershipAdmin(admin.ModelAdmin):
    list_display = ('user', 'tier', 'monthly_search_limit', 'monthly_download_limit', 'expires_at')
    search_fields = ('user__username', 'user__email')
    list_filter = ('tier',)
    autocomplete_fields = ('user',)

    def save_model(self, request, obj, form, change):
        if not change or 'tier' in form.changed_data:
            if change and 'expires_at' not in form.changed_data:
                obj.expires_at = None
            if obj.tier_id == MembershipTier.FREE:
                obj.clear_limits()
            else:
                if 'monthly_search_limit' not in form.changed_data:
                    obj.monthly_search_limit = obj.tier.monthly_search_limit
                if 'monthly_download_limit' not in form.changed_data:
                    obj.monthly_download_limit = obj.tier.monthly_download_limit
        super().save_model(request, obj, form, change)


@admin.register(PlanPurchase)
class PlanPurchaseAdmin(admin.ModelAdmin):
    list_display = ('user', 'tier', 'price_usdt', 'monthly_search_limit', 'monthly_download_limit', 'status', 'txid', 'submitted_at', 'review_link')
    list_filter = ('status', 'tier', 'submitted_at')
    search_fields = ('user__username', 'user__email', 'txid')
    fields = ('user', 'tier', 'price_usdt', 'monthly_search_limit', 'monthly_download_limit', 'payment_network', 'payment_url', 'status', 'txid', 'receipt_link', 'created_at', 'submitted_at', 'reviewed_at', 'reviewed_by', 'review_note', 'access_expires_at', 'review_link')
    readonly_fields = fields

    @admin.display(description='Receipt image')
    def receipt_link(self, obj):
        if not obj.receipt_image:
            return 'Not submitted'
        return format_html('<a href="{}" target="_blank" rel="noopener">View receipt image</a>', reverse('accounts:purchase_receipt', args=[obj.pk]))

    @admin.display(description='Review in Swifttrace')
    def review_link(self, obj):
        if not obj.pk:
            return '—'
        return format_html('<a href="{}">Open review panel</a>', reverse('accounts:purchase_review_detail', args=[obj.pk]))

    def has_module_permission(self, request):
        return request.user.is_active and request.user.is_staff and request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return request.user.is_active and request.user.is_staff and request.user.is_superuser

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(MonthlyUsage)
class MonthlyUsageAdmin(admin.ModelAdmin):
    list_display = ('email_or_visitor', 'month', 'searches', 'downloads')
    list_filter = ('month',)
    fields = readonly_fields = ('email_or_visitor', 'month', 'searches', 'downloads')

    @admin.display(description='Email / visitor')
    def email_or_visitor(self, obj):
        kind, separator, user_id = obj.identity.partition(':')
        if kind != 'user' or not separator or not user_id.isdecimal():
            return obj.identity
        email = User.objects.filter(pk=user_id).values_list('email', flat=True).first()
        if email is None:
            return 'Deleted user'
        return email or 'No email'

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return False
