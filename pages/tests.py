from django.test import TestCase, Client
from django.urls import reverse
from decimal import Decimal
from datetime import date
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
        self.assertIn("ohmyfin", content)
        self.assertIn("Ohm", content)
        self.assertIn("110,000+", content)
        self.assertIn("Before You Send", content)
        self.assertIn("After You Send", content)
        self.assertIn("Instant Wire Tracker", content)
        self.assertNotIn("HSBC-FT-20260331-59427", content)
