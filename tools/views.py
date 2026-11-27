from math import isfinite
from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from .api_input import MAX_IBAN_LENGTH, MAX_NAME_LENGTH, MAX_SMALL_API_BODY_BYTES, PayloadTooLarge, read_api_data
from .rate_limit import limit_public_api, record_public_processing_attempt
from .services import IBANValidatorService, SanctionsScreenerService


# Illustrative currency examples. No bank-specific routes or current fees are stored.
CORRIDORS_DATA = {
    'USD': {
        'currency': 'USD',
        'name': 'US Dollar (USD)',
        'example_systems': 'Fedwire / CHIPS',
        'example_timing': 'Often one or more business days, depending on the banks and route.',
    },
    'EUR': {
        'currency': 'EUR',
        'name': 'Euro (EUR)',
        'example_systems': 'SEPA / T2',
        'example_timing': 'Can range from near immediate to several business days, depending on the scheme and banks.',
    },
    'GBP': {
        'currency': 'GBP',
        'name': 'British Pound Sterling (GBP)',
        'example_systems': 'CHAPS / Faster Payments',
        'example_timing': 'Can range from hours to several business days, depending on the scheme and banks.',
    },
    'AED': {
        'currency': 'AED',
        'name': 'UAE Dirham (AED)',
        'example_systems': 'UAEFTS',
        'example_timing': 'Often one or more business days, depending on the banks and route.',
    }
}


def iban_validator_view(request):
    result = None
    iban_input = ''
    if request.method == 'POST':
        allowed, retry_after = record_public_processing_attempt(request)
        if not allowed:
            response = render(request, 'tools/iban_validator.html', {
                'iban_input': '', 'rate_limit_message': 'Too many requests. Please try again later.',
            }, status=429)
            response['Retry-After'] = str(retry_after)
            response['Cache-Control'] = 'private, no-store'
            return response
        iban_input = request.POST.get('iban', '').strip()
        if len(iban_input) > MAX_IBAN_LENGTH:
            return render(request, 'tools/iban_validator.html', {
                'iban_input': '', 'input_error': 'IBAN input is too long.',
            }, status=400)
        if iban_input:
            result = IBANValidatorService.validate(iban_input)

    return render(request, 'tools/iban_validator.html', {
        'iban_input': iban_input,
        'result': result
    })


def sanctions_screener_view(request):
    result = None
    query = ''
    if request.method == 'POST':
        allowed, retry_after = record_public_processing_attempt(request)
        if not allowed:
            response = render(request, 'tools/sanctions_screener.html', {
                'query': '', 'rate_limit_message': 'Too many requests. Please try again later.',
            }, status=429)
            response['Retry-After'] = str(retry_after)
            response['Cache-Control'] = 'private, no-store'
            return response
        query = request.POST.get('query', '').strip()
        if len(query) > MAX_NAME_LENGTH:
            return render(request, 'tools/sanctions_screener.html', {
                'query': '', 'input_error': 'Name input is too long.',
            }, status=400)
        if query:
            result = SanctionsScreenerService.screen(query)

    return render(request, 'tools/sanctions_screener.html', {
        'query': query,
        'result': result
    })


def correspondent_banks_view(request):
    """
    Illustrative currency and clearing-system reference page.
    """
    selected_currency = request.GET.get('currency', 'USD').upper()
    corridor_info = CORRIDORS_DATA.get(selected_currency, CORRIDORS_DATA['USD'])

    return render(request, 'tools/correspondent_banks.html', {
        'corridors': CORRIDORS_DATA,
        'selected_currency': selected_currency,
        'info': corridor_info
    })


def arrival_estimator_view(request):
    """
    Illustrative transit timing guide, not a payment-specific estimate.
    """
    selected_currency = request.GET.get('currency', 'USD').upper()
    corridor_info = CORRIDORS_DATA.get(selected_currency, CORRIDORS_DATA['USD'])

    return render(request, 'tools/arrival_estimator.html', {
        'corridors': CORRIDORS_DATA,
        'selected_currency': selected_currency,
        'info': corridor_info
    })


def document_validator_view(request):
    """
    MT103 text field extraction page.
    """
    return render(request, 'tools/document_validator.html')


@csrf_exempt
@limit_public_api
def api_validate_iban(request):
    if request.method == 'POST':
        try:
            data = read_api_data(request, MAX_SMALL_API_BODY_BYTES)
        except PayloadTooLarge:
            return JsonResponse({'error': 'Request body is too large.'}, status=413)
        if data is None:
            return JsonResponse({'error': 'Expected a JSON object or form fields.'}, status=400)
        iban = data.get('iban', '')
        if not isinstance(iban, str) or len(iban) > MAX_IBAN_LENGTH:
            return JsonResponse({'error': 'IBAN must be text of 128 characters or fewer.'}, status=400)
        result = IBANValidatorService.validate(iban)
        return JsonResponse(result)

    return JsonResponse({'error': 'POST method required'}, status=405)


@csrf_exempt
@limit_public_api
def api_screen_sanctions(request):
    if request.method == 'POST':
        try:
            data = read_api_data(request, MAX_SMALL_API_BODY_BYTES)
        except PayloadTooLarge:
            return JsonResponse({'error': 'Request body is too large.'}, status=413)
        if data is None:
            return JsonResponse({'error': 'Expected a JSON object or form fields.'}, status=400)
        query = data.get('query', '')
        if not isinstance(query, str) or len(query) > MAX_NAME_LENGTH:
            return JsonResponse({'error': 'Query must be text of 128 characters or fewer.'}, status=400)
        try:
            threshold = float(data.get('threshold', 0.65))
        except (ValueError, TypeError):
            threshold = 0.65
        threshold = max(0.0, min(1.0, threshold)) if isfinite(threshold) else 0.65
        result = SanctionsScreenerService.screen(query, threshold)
        return JsonResponse(result)

    return JsonResponse({'error': 'POST method required'}, status=405)
