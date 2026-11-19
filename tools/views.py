import json
from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
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
        iban_input = request.POST.get('iban', '').strip()
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
        query = request.POST.get('query', '').strip()
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
def api_validate_iban(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body.decode('utf-8'))
        except Exception:
            data = request.POST
        
        iban = data.get('iban', '')
        result = IBANValidatorService.validate(iban)
        return JsonResponse(result)

    return JsonResponse({'error': 'POST method required'}, status=405)


@csrf_exempt
def api_screen_sanctions(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body.decode('utf-8'))
        except Exception:
            data = request.POST
        
        query = data.get('query', '')
        threshold = float(data.get('threshold', 0.65))
        result = SanctionsScreenerService.screen(query, threshold)
        return JsonResponse(result)

    return JsonResponse({'error': 'POST method required'}, status=405)
