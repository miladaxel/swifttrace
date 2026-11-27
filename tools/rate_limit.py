import random
from datetime import datetime, timedelta, timezone as utc_timezone
from functools import wraps

from django.conf import settings
from django.db.models import F
from django.http import JsonResponse
from django.utils import timezone
from django.utils.crypto import salted_hmac

from tracker.rate_limit import get_client_ip

from .models import PublicProcessingRateWindow


def record_public_processing_attempt(request):
    """Count public processing POSTs across the MT103, IBAN, and name tools."""
    now = timezone.now()
    window_seconds = settings.PUBLIC_PROCESSING_WINDOW_SECONDS
    window_epoch = int(now.timestamp()) // window_seconds * window_seconds
    window_start = datetime.fromtimestamp(window_epoch, tz=utc_timezone.utc)
    retry_after = max(1, window_epoch + window_seconds - int(now.timestamp()))
    client_ip = get_client_ip(request)
    lookup_key = salted_hmac('public-processing-ip', client_ip, algorithm='sha256').hexdigest()

    if random.random() < 0.05:
        retention = max(window_seconds, 86400)
        PublicProcessingRateWindow.objects.filter(window_start__lt=now - timedelta(seconds=retention)).delete()

    PublicProcessingRateWindow.objects.get_or_create(
        lookup_key=lookup_key, window_start=window_start, defaults={'attempts': 0},
    )
    allowed = PublicProcessingRateWindow.objects.filter(
        lookup_key=lookup_key, window_start=window_start,
        attempts__lt=settings.PUBLIC_PROCESSING_RATE_LIMIT,
    ).update(attempts=F('attempts') + 1)
    return bool(allowed), retry_after


def limit_public_api(view_func):
    @wraps(view_func)
    def wrapped(request, *args, **kwargs):
        if request.method == 'POST':
            allowed, retry_after = record_public_processing_attempt(request)
            if not allowed:
                response = JsonResponse({'success': False, 'error': 'Too many requests. Please try again later.'}, status=429)
                response['Retry-After'] = str(retry_after)
                response['Cache-Control'] = 'private, no-store'
                return response
        return view_func(request, *args, **kwargs)

    return wrapped
