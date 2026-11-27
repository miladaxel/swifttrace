import random
from datetime import datetime, timedelta, timezone as utc_timezone

from django.conf import settings
from django.db.models import F
from django.utils import timezone
from django.utils.crypto import salted_hmac

from tracker.rate_limit import get_client_ip

from .models import LoginRateWindow


def record_login_attempt(request):
    """Count each anonymous login POST and return (allowed, retry_after_seconds)."""
    now = timezone.now()
    window_seconds = settings.LOGIN_RATE_WINDOW_SECONDS
    window_epoch = int(now.timestamp()) // window_seconds * window_seconds
    window_start = datetime.fromtimestamp(window_epoch, tz=utc_timezone.utc)
    retry_after = max(1, window_epoch + window_seconds - int(now.timestamp()))
    client_ip = get_client_ip(request, settings.LOGIN_TRUSTED_PROXY_IPS)
    lookup_key = salted_hmac('account-login-ip', client_ip, algorithm='sha256').hexdigest()

    if random.random() < 0.05:
        LoginRateWindow.objects.filter(window_start__lt=now - timedelta(days=1)).delete()

    LoginRateWindow.objects.get_or_create(
        lookup_key=lookup_key, window_start=window_start,
        defaults={'attempts': 0},
    )
    allowed = LoginRateWindow.objects.filter(
        lookup_key=lookup_key,
        window_start=window_start,
        attempts__lt=settings.LOGIN_RATE_LIMIT,
    ).update(attempts=F('attempts') + 1)
    return bool(allowed), retry_after
