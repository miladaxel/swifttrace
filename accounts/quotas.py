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
        membership, _ = UserMembership.objects.get_or_create(user=request.user)
        return membership.tier
    return MembershipTier.objects.get(level=MembershipTier.FREE)


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
    if request.user.is_authenticated and request.user.is_staff and request.user.has_perm('tracker.view_wiretransfer'):
        return True
    tier = tier_for(request)
    limit = getattr(tier, f'monthly_{"search" if kind == "searches" else "download"}_limit')
    identity = identity_for(request)
    month = month_start()
    MonthlyUsage.objects.get_or_create(identity=identity, month=month)
    return bool(MonthlyUsage.objects.filter(
        identity=identity, month=month, **{f'{kind}__lt': limit}
    ).update(**{kind: F(kind) + 1}))
