from django.contrib import admin

from .models import MembershipTier, UserMembership, MonthlyUsage


@admin.register(MembershipTier)
class MembershipTierAdmin(admin.ModelAdmin):
    list_display = ('level', 'monthly_search_limit', 'monthly_download_limit')
    fields = ('level', 'monthly_search_limit', 'monthly_download_limit')

    def get_readonly_fields(self, request, obj=None):
        return ('level',) if obj else ()

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(UserMembership)
class UserMembershipAdmin(admin.ModelAdmin):
    list_display = ('user', 'tier')
    search_fields = ('user__username', 'user__email')
    list_filter = ('tier',)
    autocomplete_fields = ('user',)


@admin.register(MonthlyUsage)
class MonthlyUsageAdmin(admin.ModelAdmin):
    list_display = ('identity', 'month', 'searches', 'downloads')
    list_filter = ('month',)
    readonly_fields = ('identity', 'month', 'searches', 'downloads')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return False
