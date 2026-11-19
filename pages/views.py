from django.shortcuts import render
from tracker.models import WireTransfer


def home_view(request):
    """
    Public homepage for the administrator-managed payment record portal.
    """
    total_tracked = WireTransfer.objects.filter(is_published=True).count()
    recent_wires = WireTransfer.objects.filter(is_published=True)[:4]

    return render(request, 'pages/home.html', {
        'total_tracked': total_tracked,
        'recent_wires': recent_wires,
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
    Describe service availability without inventing plans or prices.
    """
    return render(request, 'pages/pricing.html')


def scam_alert_view(request):
    """
    General guidance about checking payment document claims.
    """
    return render(request, 'pages/scam_alert.html')
