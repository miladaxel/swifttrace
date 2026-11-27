from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.core.cache import caches
from django.core.cache.utils import make_template_fragment_key
from django.urls import reverse
from decimal import Decimal
from datetime import date
import re
from tracker.models import WireTransfer


class HomePageTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.published_wire = WireTransfer.objects.create(
            uetr='b4e791d2-a6f5-48c3-89d1-5c82e7a9b3f0',
            reference_number='HSBC-FT-20260331-59427',
            date_of_payment=date(2026, 3, 31),
            amount=Decimal('79998940.00'),
            currency='EUR',
            sender_name='Global Client Ltd',
            beneficiary_name='Target Corp',
            sender_bank_name='HSBC Bank plc',
            beneficiary_bank_name='Deutsche Bank',
            charge_type='OUR',
            status='HOLD',
            is_published=True
        )

    def test_homepage_renders_correctly(self):
        response = self.client.get(reverse('pages:home'))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')

        # Verify branding & key sections
        self.assertIn("Find a cross-border payment record", content)
        self.assertIn("Swifttrace", content)
        self.assertIn("Swift", content)
        self.assertIn("110,000+", content)
        self.assertIn("Before You Send", content)
        self.assertIn("After You Send", content)
        self.assertIn("Instant Wire Tracker", content)
        self.assertNotIn("HSBC-FT-20260331-59427", content)

    def test_homepage_cache_keeps_user_and_csrf_content_dynamic(self):
        fragment_cache = caches['home_fragments']
        fragment_cache.clear()
        anonymous = Client()
        anonymous_response = anonymous.get(reverse('pages:home'))

        key = make_template_fragment_key('home_static_sections_v1')
        cached_fragment = fragment_cache.get(key)
        self.assertIsNotNone(cached_fragment)
        self.assertIn('Banks & BIC Codes', cached_fragment)
        self.assertNotIn('csrfmiddlewaretoken', cached_fragment)

        user = get_user_model().objects.create_user(username='cache-member', password='test-password')
        authenticated = Client()
        authenticated.force_login(user)
        authenticated_response = authenticated.get(reverse('pages:home'))

        self.assertNotIn('Account: cache-member', anonymous_response.content.decode())
        self.assertIn('Account: cache-member', authenticated_response.content.decode())
        token_pattern = rb'name="csrfmiddlewaretoken" value="([^"]+)"'
        anonymous_token = re.search(token_pattern, anonymous_response.content).group(1)
        authenticated_token = re.search(token_pattern, authenticated_response.content).group(1)
        self.assertNotEqual(anonymous_token, authenticated_token)
