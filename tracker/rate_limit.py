import random
from datetime import datetime, timedelta, timezone as utc_timezone
from ipaddress import ip_address
from math import ceil
from uuid import UUID

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import F
from django.utils import timezone
from django.utils.crypto import salted_hmac

from .models import AccountSearchAttempt, ResultViewWindow, SearchRateWindow


def get_client_ip(request, trusted_proxy_ips=None):
    remote = request.META.get('REMOTE_ADDR') or 'unknown'
    trusted_proxy_ips = settings.WIRE_TRUSTED_PROXY_IPS if trusted_proxy_ips is None else trusted_proxy_ips
    if remote not in trusted_proxy_ips:
        return remote
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '')
    for candidate in reversed(forwarded.split(',')):
        candidate = candidate.strip()
        try:
            ip_address(candidate)
        except ValueError:
            continue
        if candidate not in trusted_proxy_ips:
            return candidate
    return remote


def cleanup_expired_search_windows(now=None):
    """Delete search rate windows older than 1 day."""
    now = now or timezone.now()
    return SearchRateWindow.objects.filter(window_start__lt=now - timedelta(days=1)).delete()


def record_search_attempt(request):
    """Return (allowed, seconds_until_reset) for an IP's search window."""
    now = timezone.now()
    window_seconds = settings.WIRE_SEARCH_WINDOW_SECONDS
    window_epoch = int(now.timestamp()) // window_seconds * window_seconds
    window_start = datetime.fromtimestamp(window_epoch, tz=utc_timezone.utc)
    retry_after = max(1, window_epoch + window_seconds - int(now.timestamp()))
    client_ip = get_client_ip(request)
    lookup_key = salted_hmac('wire-transfer-search', client_ip, algorithm='sha256').hexdigest()

    # Probabilistic cleanup (~5% chance per request) to prevent table lock contention
    if random.random() < 0.05:
        cleanup_expired_search_windows(now)

    SearchRateWindow.objects.get_or_create(
        lookup_key=lookup_key, window_start=window_start,
        defaults={'attempts': 0},
    )
    allowed = SearchRateWindow.objects.filter(
        lookup_key=lookup_key,
        window_start=window_start,
        attempts__lt=settings.WIRE_SEARCH_LIMIT,
    ).update(attempts=F('attempts') + 1)
    return bool(allowed), retry_after


def record_account_search_attempt(request):
    """Limit signed-in accounts to a rolling window of search POSTs."""
    now = timezone.now()
    window = timedelta(seconds=settings.ACCOUNT_SEARCH_WINDOW_SECONDS)
    cutoff = now - window

    if random.random() < 0.01:
        AccountSearchAttempt.objects.filter(created_at__lte=now - max(window, timedelta(days=1))).delete()

    # Lock the user row so concurrent requests from the same account share one count.
    with transaction.atomic():
        get_user_model().objects.select_for_update().get(pk=request.user.pk)
        recent = AccountSearchAttempt.objects.filter(user_id=request.user.pk, created_at__gt=cutoff)
        if recent.count() >= settings.ACCOUNT_SEARCH_RATE_LIMIT:
            oldest = recent.order_by('created_at').values_list('created_at', flat=True).first()
            retry_after = max(1, ceil((oldest + window - now).total_seconds()))
            return False, retry_after
        AccountSearchAttempt.objects.create(user_id=request.user.pk, created_at=now)
    return True, 0


def start_result_view_window(transfer):
    now = timezone.now()
    if random.random() < 0.01:
        ResultViewWindow.objects.filter(expires_at__lt=now - timedelta(days=1)).delete()
    return ResultViewWindow.objects.create(
        transfer=transfer,
        expires_at=now + timedelta(seconds=settings.WIRE_RESULT_ACCESS_SECONDS),
    )


def record_result_view(grant_id, transfer_id):
    """Return True if counted, False if exhausted, or None if access is invalid."""
    try:
        grant_id = UUID(str(grant_id))
    except (ValueError, TypeError, AttributeError):
        return None
    active = ResultViewWindow.objects.filter(
        pk=grant_id, transfer_id=transfer_id, expires_at__gt=timezone.now(),
    )
    if active.filter(views__lt=settings.WIRE_RESULT_VIEW_LIMIT).update(views=F('views') + 1):
        return True
    return False if active.exists() else None
