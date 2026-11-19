import random
from datetime import datetime, timedelta, timezone as utc_timezone
from ipaddress import ip_address

from django.conf import settings
from django.db.models import F
from django.utils import timezone
from django.utils.crypto import salted_hmac

from .models import SearchRateWindow


def get_client_ip(request):
    remote = request.META.get('REMOTE_ADDR') or 'unknown'
    if remote not in settings.WIRE_TRUSTED_PROXY_IPS:
        return remote
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '')
    for candidate in reversed(forwarded.split(',')):
        candidate = candidate.strip()
        try:
            ip_address(candidate)
        except ValueError:
            continue
        if candidate not in settings.WIRE_TRUSTED_PROXY_IPS:
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
