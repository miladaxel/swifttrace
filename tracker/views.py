from django.conf import settings
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.http import JsonResponse, Http404, FileResponse, HttpResponse
from django.core.exceptions import PermissionDenied
from django.contrib import messages
from django.contrib.auth.views import redirect_to_login
from django.contrib.admin.views.decorators import staff_member_required
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.cache import never_cache
from django.utils import timezone
from .models import WireTransfer, TransferSourceDocument, TrackerSettings
from .services import MT103Parser
from .forms import WireTransferSearchForm
from .rate_limit import (
    record_account_search_attempt, record_result_view, record_search_attempt,
    start_result_view_window,
)
from tools.api_input import MAX_MT103_JSON_BODY_BYTES, MAX_MT103_TEXT_LENGTH, PayloadTooLarge, read_api_data
from tools.rate_limit import limit_public_api
from accounts.quotas import consume_quota


@never_cache
def wire_transfer_view(request):
    """Find only records entered and published by an administrator."""
    if TrackerSettings.is_login_required() and not request.user.is_authenticated:
        messages.info(request, 'Please sign in or create an account to search and track wire transfers.')
        return redirect_to_login(request.get_full_path(), login_url=settings.LOGIN_URL)

    form = WireTransferSearchForm(request.POST or None)
    if request.method == 'POST':
        if request.user.is_authenticated:
            allowed, retry_after = record_account_search_attempt(request)
        else:
            allowed, retry_after = record_search_attempt(request)
        if not allowed:
            response = render(request, 'tracker/wire_transfer.html', {
                'form': form,
                'rate_limit_message': 'Too many searches. Please try again later.',
            }, status=429)
            response['Retry-After'] = str(retry_after)
            return response
    if request.method == 'POST' and form.is_valid():
        data = form.cleaned_data
        matches = WireTransfer.objects.filter(is_published=True)
        if data['uetr']:
            matches = matches.filter(uetr__iexact=data['uetr'])
        if data['reference']:
            matches = matches.filter(reference_number__iexact=data['reference'])
        if data['date_of_payment']:
            matches = matches.filter(date_of_payment=data['date_of_payment'])
        if data['amount'] is not None:
            matches = matches.filter(amount=data['amount'])
        if data['currency']:
            matches = matches.filter(currency__iexact=data['currency'])

        found = list(matches[:2])
        if not found:
            form.add_error(None, 'No published document matches these details. Check the UETR or reference, date and amount. If the details are correct, ask the team that provided this service whether the record has been published.')
        elif len(found) > 1:
            form.add_error(None, 'More than one document matches. Add the UETR or currency to narrow your search.')
        else:
            if not consume_quota(request, 'searches'):
                return render(request, 'tracker/wire_transfer.html', {
                    'form': form,
                    'rate_limit_message': 'Monthly search limit reached. Your quota resets next month.',
                }, status=429)
            grant = start_result_view_window(found[0])
            request.session['found_transfer_id'] = found[0].pk
            request.session['found_transfer_expires_at'] = int(grant.expires_at.timestamp())
            request.session['found_transfer_view_grant'] = str(grant.pk)
            return redirect('tracker:tracking_result', transfer_id=found[0].pk)

    return render(request, 'tracker/wire_transfer.html', {'form': form})


@never_cache
def tracking_result_view(request, transfer_id):
    if TrackerSettings.is_login_required() and not request.user.is_authenticated:
        messages.info(request, 'Please sign in or create an account to view wire transfer details.')
        return redirect_to_login(request.get_full_path(), login_url=settings.LOGIN_URL)

    transfer = get_object_or_404(WireTransfer, pk=transfer_id)
    can_view_full = request.user.is_staff and request.user.has_perm('tracker.view_wiretransfer')
    if not can_view_full and (
        not transfer.is_published
        or request.session.get('found_transfer_id') != transfer.pk
        or request.session.get('found_transfer_expires_at', 0) <= int(timezone.now().timestamp())
    ):
        raise Http404('Search for this document first.')
    if not can_view_full:
        result_view = record_result_view(request.session.get('found_transfer_view_grant'), transfer.pk)
        if result_view is None:
            raise Http404('Search for this document first.')
        if not result_view:
            response = HttpResponse('Result view limit reached. Search again to reopen this record.', status=429)
            response['X-Robots-Tag'] = 'noindex, nofollow'
            return response
    response = render(request, 'tracker/tracking_result.html', {
        'transfer': transfer, 'can_view_full': can_view_full,
    })
    response['X-Robots-Tag'] = 'noindex, nofollow'
    return response


def download_source_document(request, document_id):
    document = get_object_or_404(TransferSourceDocument, pk=document_id)
    transfer = document.transfer

    is_staff_authorized = (
        request.user.is_authenticated
        and request.user.is_staff
        and request.user.has_perm('tracker.view_wiretransfer')
    )

    has_search_session = (
        transfer.is_published
        and request.session.get('found_transfer_id') == transfer.pk
        and request.session.get('found_transfer_expires_at', 0) > int(timezone.now().timestamp())
    )

    if TrackerSettings.is_login_required() and not request.user.is_authenticated:
        return redirect_to_login(request.get_full_path(), login_url=settings.LOGIN_URL)

    if not is_staff_authorized and not has_search_session:
        if request.user.is_authenticated and request.user.is_staff:
            raise PermissionDenied
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path(), login_url=settings.LOGIN_URL)
        raise Http404('Search for this document first.')

    try:
        document.file.open('rb')
    except (OSError, ValueError):
        raise Http404('Source file is unavailable.')
    if not consume_quota(request, 'downloads'):
        document.file.close()
        return HttpResponse('Monthly download limit reached. Your quota resets next month.', status=429)
    response = FileResponse(
        document.file, as_attachment=True,
        filename=document.original_filename or 'source-document',
        content_type='application/octet-stream',
    )
    response['Cache-Control'] = 'private, no-store'
    response['X-Content-Type-Options'] = 'nosniff'
    return response


@never_cache
def download_transfer_statement(request, transfer_id):
    if TrackerSettings.is_login_required() and not request.user.is_authenticated:
        return redirect_to_login(request.get_full_path(), login_url=settings.LOGIN_URL)

    transfer = get_object_or_404(WireTransfer, pk=transfer_id)
    can_view_full = request.user.is_authenticated and request.user.is_staff and request.user.has_perm('tracker.view_wiretransfer')
    has_search_session = (
        transfer.is_published
        and request.session.get('found_transfer_id') == transfer.pk
        and request.session.get('found_transfer_expires_at', 0) > int(timezone.now().timestamp())
    )

    if not can_view_full and not has_search_session:
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path(), login_url=settings.LOGIN_URL)
        raise Http404('Search for this document first.')

    if not consume_quota(request, 'downloads'):
        return HttpResponse('Monthly download limit reached. Your quota resets next month.', status=429)

    lines = [
        "=" * 78,
        "                         SWIFTTRACE WIRE TRANSFER RECORD",
        "=" * 78,
        f"Generated At:       {timezone.now().strftime('%Y-%m-%d %H:%M:%S UTC')}",
        f"Status:             {transfer.get_status_display()} ({transfer.status})",
    ]
    if transfer.status_observed_at:
        lines.append(f"Status Observed:    {transfer.status_observed_at.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    if transfer.eta_delivery:
        lines.append(f"Estimated Delivery: {transfer.eta_delivery.strftime('%Y-%m-%d %H:%M:%S UTC')}")

    lines.extend([
        "",
        "-" * 78,
        "PAYMENT DETAILS",
        "-" * 78,
        f"UETR (Field 121):    {transfer.uetr or 'N/A'}",
        f"Reference (Field 20): {transfer.reference_number or 'N/A'}",
        f"Date of Payment:     {transfer.date_of_payment}",
        f"Amount:              {transfer.currency} {transfer.amount:,.2f}",
        f"Charge Model:        {transfer.get_charge_type_display()}",
        "",
        "-" * 78,
        "PARTIES & BANKS",
        "-" * 78,
        f"Ordering Customer:   {transfer.sender_name or 'N/A'}",
        f"Sender Account:      {transfer.sender_account if can_view_full else transfer.masked_sender_account}",
        f"Sender Bank:         {transfer.sender_bank_name or 'N/A'} ({transfer.sender_bank_bic or 'N/A'})",
        "",
        f"Beneficiary:         {transfer.beneficiary_name or 'N/A'}",
        f"Beneficiary Account: {transfer.beneficiary_account if can_view_full else transfer.masked_beneficiary_account}",
        f"Beneficiary Bank:    {transfer.beneficiary_bank_name or 'N/A'} ({transfer.beneficiary_bank_bic or 'N/A'})",
    ])

    steps = list(transfer.steps.all())
    if steps:
        lines.extend([
            "",
            "-" * 78,
            "RECORDED PAYMENT STAGES",
            "-" * 78,
        ])
        for step in steps:
            lines.append(
                f"  [{step.step_order}] {step.timestamp.strftime('%Y-%m-%d %H:%M UTC')} | "
                f"{step.bank_name} ({step.bank_bic}) - {step.role} | "
                f"Status: {step.status_label} ({step.status_code})"
            )
            if step.fee_deducted:
                lines.append(f"      Fee Deducted: {transfer.currency} {step.fee_deducted:,.2f}")

    lines.extend([
        "",
        "=" * 78,
        "Notice: This statement contains record data verified and entered in Swifttrace.",
        "=" * 78,
    ])

    content = "\n".join(lines)
    filename = f"wire-statement-{transfer.uetr or transfer.reference_number or transfer.pk}.txt"
    response = HttpResponse(content, content_type='text/plain; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    response['Cache-Control'] = 'private, no-store'
    response['X-Content-Type-Options'] = 'nosniff'
    return response


@csrf_exempt
@limit_public_api
def parse_mt103_api(request):
    """
    Extract selected fields from MT103-like text. No authenticity check is made.
    """
    if request.method == 'POST':
        raw_text = ''
        
        # Handle uploaded file if present
        if request.FILES.get('document'):
            uploaded_file = request.FILES['document']
            if uploaded_file.size > 2 * 1024 * 1024:
                return JsonResponse({'success': False, 'error': 'Uploaded file must be 2 MB or smaller.'}, status=400)
            try:
                raw_text = uploaded_file.read().decode('utf-8', errors='ignore')
            except (OSError, UnicodeError):
                return JsonResponse({'success': False, 'error': 'Failed to read file.'}, status=400)
        else:
            try:
                data = read_api_data(request, MAX_MT103_JSON_BODY_BYTES)
            except PayloadTooLarge:
                return JsonResponse({'success': False, 'error': 'Request body is too large.'}, status=413)
            if data is None:
                return JsonResponse({'success': False, 'error': 'Expected a JSON object or form fields.'}, status=400)
            raw_text = data.get('raw_text', '')

        if not isinstance(raw_text, str):
            return JsonResponse({'success': False, 'error': 'MT103 text must be a string.'}, status=400)
        if len(raw_text) > MAX_MT103_TEXT_LENGTH:
            return JsonResponse({'success': False, 'error': 'MT103 text must be 128 KB or smaller.'}, status=400)
        if not raw_text.strip():
            return JsonResponse({'success': False, 'error': 'No MT103 text provided.'}, status=400)

        parsed_data = MT103Parser.parse(raw_text)
        return JsonResponse({
            'success': True,
            'data': parsed_data
        })

    return JsonResponse({'error': 'POST method required'}, status=405)


@staff_member_required
def toggle_tracker_login_requirement(request):
    if request.method == 'POST':
        settings_obj = TrackerSettings.get_settings()
        settings_obj.require_login = not settings_obj.require_login
        settings_obj.updated_by = request.user
        settings_obj.save()
        status_str = "now requires registration / login" if settings_obj.require_login else "is now open to the public without login"
        messages.success(request, f"Wire Tracker access updated: Access {status_str}.")
    next_url = request.POST.get('next') or request.META.get('HTTP_REFERER') or reverse('dashboard:index')
    return redirect(next_url)

