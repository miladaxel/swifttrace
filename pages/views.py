from django.shortcuts import render
from tracker.models import WireTransfer
from accounts.models import MembershipTier


def home_view(request):
    """
    Public homepage for the administrator-managed payment record portal.
    """
    total_tracked = WireTransfer.objects.filter(is_published=True).count()

    return render(request, 'pages/home.html', {
        'total_tracked': total_tracked,
    })


def for_business_view(request):
    """
    Explain the current team workflow.
    """
    return render(request, 'pages/for_business.html')


def about_view(request):
    """
    Explain the independent prototype and its limits.
    """
    return render(request, 'pages/about.html')


def pricing_view(request):
    """
    Show the currently configured monthly usage limits.
    """
    tiers = [MembershipTier.objects.get(level=level) for level, _ in MembershipTier.LEVELS]
    return render(request, 'pages/pricing.html', {'tiers': tiers})


def scam_alert_view(request):
    """
    General guidance about checking payment document claims.
    """
    return render(request, 'pages/scam_alert.html')
