from django.shortcuts import render
from django.db.models import Count, Sum, Q
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import permission_required
from tracker.models import WireTransfer, TrackerSettings


@staff_member_required
@permission_required('tracker.view_wiretransfer', raise_exception=True)
def dashboard_view(request):
    """
    Payments Dashboard matching Ohmyfin's 'Payments Dashboard' button.
    Displays overview of all tracked wires, statuses, metrics and actions.
    """
    status_filter = request.GET.get('status', '')
    query = request.GET.get('q', '').strip()

    transfers = WireTransfer.objects.all()

    if status_filter:
        transfers = transfers.filter(status=status_filter)

    if query:
        clean_q = query.replace(' ', '').replace('-', '')
        search_filter = (
            Q(uetr__icontains=query) |
            Q(reference_number__icontains=query) |
            Q(beneficiary_name__icontains=query) |
            Q(sender_name__icontains=query) |
            Q(sender_bank_name__icontains=query) |
            Q(beneficiary_bank_name__icontains=query) |
            Q(sender_account__icontains=query) |
            Q(beneficiary_account__icontains=query) |
            Q(currency__iexact=query)
        )
        if len(clean_q) >= 8:
            # Also match UETRs with or without hyphens
            search_filter |= Q(uetr__icontains=clean_q)

        transfers = transfers.filter(search_filter)

    # Statistics
    total_count = WireTransfer.objects.count()
    completed_count = WireTransfer.objects.filter(status='ACCC').count()
    in_transit_count = WireTransfer.objects.filter(status='ACSP').count()
    held_count = WireTransfer.objects.filter(status__in=['HOLD', 'RJCT']).count()
    
    recent_transfers = transfers[:20]

    return render(request, 'dashboard/index.html', {
        'transfers': recent_transfers,
        'total_count': total_count,
        'completed_count': completed_count,
        'in_transit_count': in_transit_count,
        'held_count': held_count,
        'selected_status': status_filter,
        'search_query': query,
        'tracker_settings': TrackerSettings.get_settings(),
    })
