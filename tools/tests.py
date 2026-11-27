import json
from django.test import TestCase, Client, override_settings
from django.urls import reverse
from .models import PublicProcessingRateWindow


class ToolsApiTests(TestCase):
    def setUp(self):
        self.client = Client()

    def test_api_screen_sanctions_valid(self):
        response = self.client.post(
            reverse('tools:api_screen_sanctions'),
            data=json.dumps({'query': 'Sample Entity Alpha', 'threshold': 0.7}),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['risk_level'], 'SAMPLE MATCH')
        self.assertGreater(data['total_matches'], 0)

    def test_api_screen_sanctions_invalid_threshold(self):
        # String threshold that cannot be converted to float
        response = self.client.post(
            reverse('tools:api_screen_sanctions'),
            data=json.dumps({'query': 'Sample Entity Alpha', 'threshold': 'not-a-number'}),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['risk_level'], 'SAMPLE MATCH')

        # None / null threshold
        response_null = self.client.post(
            reverse('tools:api_screen_sanctions'),
            data=json.dumps({'query': 'Sample Entity Alpha', 'threshold': None}),
            content_type='application/json'
        )
        self.assertEqual(response_null.status_code, 200)

    def test_api_screen_sanctions_method_not_allowed(self):
        response = self.client.get(reverse('tools:api_screen_sanctions'))
        self.assertEqual(response.status_code, 405)

    def test_api_validate_iban_post(self):
        response = self.client.post(
            reverse('tools:api_validate_iban'),
            data=json.dumps({'iban': 'GB29NWBK60161331926819'}),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['is_valid'])

        response_get = self.client.get(reverse('tools:api_validate_iban'))
        self.assertEqual(response_get.status_code, 405)

    def test_api_rejects_invalid_json_types_and_oversized_inputs(self):
        iban_url = reverse('tools:api_validate_iban')
        sanctions_url = reverse('tools:api_screen_sanctions')
        for payload in ('[]', '{', json.dumps({'iban': 123}), json.dumps({'iban': 'A' * 129})):
            self.assertEqual(self.client.post(iban_url, payload, content_type='application/json').status_code, 400)
        for payload in ('[]', json.dumps({'query': ['name']}), json.dumps({'query': 'A' * 129})):
            self.assertEqual(self.client.post(sanctions_url, payload, content_type='application/json').status_code, 400)
        self.assertEqual(self.client.post(iban_url, json.dumps({'iban': 'A' * 5000}), content_type='application/json').status_code, 413)
        self.assertEqual(self.client.post(reverse('tools:iban_validator'), {'iban': 'A' * 129}).status_code, 400)
        self.assertEqual(self.client.post(reverse('tools:sanctions_screener'), {'query': 'A' * 129}).status_code, 400)

    @override_settings(PUBLIC_PROCESSING_RATE_LIMIT=2)
    def test_public_processing_limit_is_shared_by_apis_and_forms_per_ip(self):
        iban_url = reverse('tools:api_validate_iban')
        sanctions_url = reverse('tools:sanctions_screener')
        self.assertEqual(self.client.post(iban_url, {'iban': 'GB29NWBK60161331926819'}, REMOTE_ADDR='198.51.100.10').status_code, 200)
        self.assertEqual(self.client.post(sanctions_url, {'query': 'Sample Entity Alpha'}, REMOTE_ADDR='198.51.100.10').status_code, 200)
        blocked = self.client.post(reverse('tracker:parse_mt103_api'),
                                   data=json.dumps({'raw_text': ':20:REF-123'}), content_type='application/json',
                                   REMOTE_ADDR='198.51.100.10')
        self.assertEqual(blocked.status_code, 429)
        self.assertGreater(int(blocked['Retry-After']), 0)
        self.assertIn('no-store', blocked['Cache-Control'])
        blocked_form = self.client.post(sanctions_url, {'query': 'Sample Entity Alpha'}, REMOTE_ADDR='198.51.100.10')
        self.assertContains(blocked_form, 'Too many requests', status_code=429)
        self.assertEqual(PublicProcessingRateWindow.objects.get().attempts, 2)
        self.assertEqual(self.client.post(iban_url, {'iban': 'GB29NWBK60161331926819'}, REMOTE_ADDR='198.51.100.11').status_code, 200)

    @override_settings(PUBLIC_PROCESSING_RATE_LIMIT=1, WIRE_TRUSTED_PROXY_IPS={'10.0.0.1'})
    def test_public_api_limit_uses_forwarded_ip_only_from_trusted_proxy(self):
        url = reverse('tools:api_validate_iban')
        query = {'iban': 'GB29NWBK60161331926819'}
        self.assertEqual(self.client.post(url, query, REMOTE_ADDR='10.0.0.1', HTTP_X_FORWARDED_FOR='198.51.100.20').status_code, 200)
        self.assertEqual(self.client.post(url, query, REMOTE_ADDR='10.0.0.1', HTTP_X_FORWARDED_FOR='198.51.100.21').status_code, 200)
        self.assertEqual(self.client.post(url, query, REMOTE_ADDR='10.0.0.1', HTTP_X_FORWARDED_FOR='198.51.100.20').status_code, 429)
