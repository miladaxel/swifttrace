import json
from django.test import TestCase, Client
from django.urls import reverse


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
