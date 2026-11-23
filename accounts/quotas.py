from datetime import date
from django.db.models import F
from django.utils import timezone
from django.utils.crypto import salted_hmac
from tracker.rate_limit import get_client_ip

from .models import MembershipTier, MonthlyUsage, UserMembership


def visitor_identity(request):
    return 'ip:' + salted_hmac('monthly-membership-quota', get_client_ip(request), algorithm='sha256').hexdigest()


def identity_for(request):
    if request.user.is_authenticated:
        return f'user:{request.user.pk}'
    return visitor_identity(request)


def tier_for(request):
    if request.user.is_authenticated:
        return membership_for(request.user).tier
    return MembershipTier.objects.get(level=MembershipTier.FREE)


def membership_for(user):
    membership, _ = UserMembership.objects.get_or_create(user=user)
    if membership.expires_at and membership.expires_at <= timezone.now():
        membership.tier_id = MembershipTier.FREE
        membership.expires_at = None
        membership.clear_limits()
        membership.save(update_fields=['tier', 'expires_at', 'monthly_search_limit', 'monthly_download_limit'])
    return membership


def expire_memberships():
    return UserMembership.objects.filter(expires_at__lte=timezone.now()).update(
        tier_id=MembershipTier.FREE, expires_at=None,
        monthly_search_limit=None, monthly_download_limit=None,
    )


def limits_for(request):
    if not request.user.is_authenticated:
        tier = MembershipTier.objects.get(level=MembershipTier.FREE)
        return tier.monthly_search_limit, tier.monthly_download_limit

    membership = membership_for(request.user)
    tier = membership.tier
    if tier.level == MembershipTier.FREE:
        return tier.monthly_search_limit, tier.monthly_download_limit

    missing = []
    if membership.monthly_search_limit is None:
        membership.monthly_search_limit = tier.monthly_search_limit
        missing.append('monthly_search_limit')
    if membership.monthly_download_limit is None:
        membership.monthly_download_limit = tier.monthly_download_limit
        missing.append('monthly_download_limit')
    if missing:
        membership.save(update_fields=missing)
    return membership.monthly_search_limit, membership.monthly_download_limit


def month_start():
    today = timezone.localdate()
    return date(today.year, today.month, 1)


def quota_status(request):
    tier = tier_for(request)
    usage, _ = MonthlyUsage.objects.get_or_create(identity=identity_for(request), month=month_start())
    return tier, usage


def consume_quota(request, kind):
    """Atomically reserve one monthly search or download; return True when allowed."""
    if kind not in ('searches', 'downloads'):
        raise ValueError('Invalid quota kind')
    if request.user.is_authenticated and request.user.is_superuser:
        return True
    search_limit, download_limit = limits_for(request)
    limit = search_limit if kind == 'searches' else download_limit
    identity = identity_for(request)
    month = month_start()
    MonthlyUsage.objects.get_or_create(identity=identity, month=month)
    return bool(MonthlyUsage.objects.filter(
        identity=identity, month=month, **{f'{kind}__lt': limit}
    ).update(**{kind: F(kind) + 1}))
