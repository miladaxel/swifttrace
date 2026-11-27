from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from datetime import date, datetime, timedelta, timezone as datetime_timezone
from decimal import Decimal
from io import BytesIO
from tempfile import TemporaryDirectory
from unittest.mock import patch
from django.test import RequestFactory
from .models import MembershipTier, MonthlyUsage, UserMembership
from .models import PlanPurchase, LoginRateWindow
from .quotas import consume_quota, quota_status
from .quotas import membership_for
from .purchase_review import one_month_later
from tracker.storage import private_document_storage
from PIL import Image
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

User = get_user_model()


class PlanPurchaseTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='buyer', password='test-password')
        self.client.force_login(self.user)
        self.silver = MembershipTier.objects.get(level='silver')
        self.silver.monthly_price_usdt = Decimal('12.50')
        self.silver.payment_url = 'https://pay.example/silver'
        self.silver.payment_network = 'TRC20'
        self.silver.save()

    @staticmethod
    def receipt():
        buffer = BytesIO()
        Image.new('RGB', (32, 32), 'white').save(buffer, format='PNG')
        return SimpleUploadedFile('receipt.png', buffer.getvalue(), content_type='image/png')

    def test_select_plan_shows_frozen_payment_link_and_qr(self):
        start = reverse('accounts:start_plan_purchase', args=['silver'])
        selected = self.client.post(start)
        self.assertEqual(selected.status_code, 302)
        purchase = PlanPurchase.objects.get(user=self.user)
        self.assertEqual(purchase.price_usdt, Decimal('12.50'))
        self.assertEqual(purchase.payment_network, 'TRC20')
        self.assertEqual(self.client.post(start).url, selected.url)

        self.silver.monthly_price_usdt = Decimal('15.00')
        self.silver.payment_url = 'https://pay.example/new-silver'
        self.silver.save()
        detail = self.client.get(selected.url)
        self.assertContains(detail, '12.50')
        self.assertContains(detail, 'https://pay.example/silver')
        self.assertNotContains(detail, 'https://pay.example/new-silver')
        qr = self.client.get(reverse('accounts:purchase_qr', args=[purchase.pk]))
        self.assertEqual(qr.status_code, 200)
        self.assertEqual(qr['Content-Type'], 'image/png')
        self.assertEqual(qr.content[:8], b'\x89PNG\r\n\x1a\n')
        self.assertIn('no-store', qr['Cache-Control'])

    def test_demo_payment_is_clearly_marked_and_can_start(self):
        self.silver.payment_url = 'https://example.com/?swifttrace-demo=silver'
        self.silver.payment_network = 'Demo only'
        self.silver.save(update_fields=['payment_url', 'payment_network'])
        pricing = self.client.get(reverse('pages:pricing'))
        self.assertContains(pricing, 'Test payment')
        self.assertContains(pricing, 'Do not send real USDT')
        self.assertNotContains(pricing, 'coming soon')

        response = self.client.post(reverse('accounts:start_plan_purchase', args=['silver']))
        self.assertEqual(response.status_code, 302)
        detail = self.client.get(response.url)
        self.assertContains(detail, 'https://example.com/?swifttrace-demo=silver')

    def test_payment_proof_is_private_and_waits_for_review(self):
        self.client.post(reverse('accounts:start_plan_purchase', args=['silver']))
        purchase = PlanPurchase.objects.get(user=self.user)
        detail_url = reverse('accounts:plan_purchase', args=[purchase.pk])
        with TemporaryDirectory() as root, patch.object(private_document_storage, 'location', root):
            invalid = self.client.post(detail_url, {
                'txid': 'ABC123', 'receipt_image': SimpleUploadedFile('receipt.png', b'not an image'),
            })
            self.assertEqual(invalid.status_code, 200)
            self.assertEqual(PlanPurchase.objects.get(pk=purchase.pk).status, PlanPurchase.AWAITING_PAYMENT)

            submitted = self.client.post(detail_url, {'txid': 'ABC123', 'receipt_image': self.receipt()})
            self.assertEqual(submitted.status_code, 302)
            purchase.refresh_from_db()
            self.assertEqual(purchase.status, PlanPurchase.SUBMITTED)
            self.assertEqual(purchase.txid, 'abc123')
            self.assertIsNotNone(purchase.submitted_at)
            self.assertEqual(UserMembership.objects.get(user=self.user).tier_id, 'free')
            self.assertEqual(
                self.client.post(reverse('accounts:start_plan_purchase', args=['silver'])).url,
                detail_url,
            )
            self.assertEqual(PlanPurchase.objects.filter(user=self.user, tier=self.silver).count(), 1)
            self.assertEqual(self.client.get(reverse('accounts:purchase_qr', args=[purchase.pk])).status_code, 404)
            with self.assertRaises(ValueError):
                _ = purchase.receipt_image.url

            receipt_url = reverse('accounts:purchase_receipt', args=[purchase.pk])
            image_response = self.client.get(receipt_url)
            self.assertEqual(image_response.status_code, 200)
            self.assertEqual(image_response['Content-Type'], 'image/png')
            image_response.close()

            other = User.objects.create_user(username='other-buyer', password='test-password')
            self.client.force_login(other)
            self.assertEqual(self.client.get(detail_url).status_code, 404)
            self.assertEqual(self.client.get(reverse('accounts:purchase_qr', args=[purchase.pk])).status_code, 404)
            self.assertEqual(self.client.get(receipt_url).status_code, 404)

            admin_user = User.objects.create_superuser(username='purchase-admin', email='purchase-admin@example.com', password='test-password')
            self.client.force_login(admin_user)
            admin_image = self.client.get(receipt_url)
            self.assertEqual(admin_image.status_code, 200)
            admin_image.close()
            admin_detail = self.client.get(reverse('admin:accounts_planpurchase_change', args=[purchase.pk]))
            self.assertContains(admin_detail, 'abc123')
            self.assertContains(admin_detail, receipt_url)

    def test_unconfigured_and_free_plans_cannot_start_payment(self):
        self.assertEqual(self.client.post(reverse('accounts:start_plan_purchase', args=['free'])).status_code, 404)
        gold = MembershipTier.objects.get(level='gold')
        gold.monthly_price_usdt = Decimal('29.00')
        gold.save()
        response = self.client.post(reverse('accounts:start_plan_purchase', args=['gold']))
        self.assertRedirects(response, reverse('pages:pricing'))
        self.assertFalse(PlanPurchase.objects.exists())

    def test_transaction_id_cannot_be_reused_for_another_purchase(self):
        self.client.post(reverse('accounts:start_plan_purchase', args=['silver']))
        first = PlanPurchase.objects.get(user=self.user)
        gold = MembershipTier.objects.get(level='gold')
        gold.monthly_price_usdt = Decimal('29.00')
        gold.payment_url = 'https://pay.example/gold'
        gold.payment_network = 'TRC20'
        gold.save()
        self.client.post(reverse('accounts:start_plan_purchase', args=['gold']))
        second = PlanPurchase.objects.get(user=self.user, tier=gold)
        with TemporaryDirectory() as root, patch.object(private_document_storage, 'location', root):
            self.assertEqual(self.client.post(reverse('accounts:plan_purchase', args=[first.pk]), {
                'txid': 'SameTransaction123', 'receipt_image': self.receipt(),
            }).status_code, 302)
            duplicate = self.client.post(reverse('accounts:plan_purchase', args=[second.pk]), {
                'txid': 'SAMETRANSACTION123', 'receipt_image': self.receipt(),
            })
            self.assertContains(duplicate, 'already been submitted')
            second.refresh_from_db()
            self.assertEqual(second.status, PlanPurchase.AWAITING_PAYMENT)
            self.assertIsNone(second.txid)

    def test_anonymous_user_returns_to_plans_after_login(self):
        self.client.logout()
        response = self.client.post(reverse('accounts:start_plan_purchase', args=['silver']))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('accounts:login'), response.url)
        self.assertIn(reverse('pages:pricing'), response.url)
        self.assertFalse(PlanPurchase.objects.exists())


class PurchaseReviewTests(TestCase):
    def setUp(self):
        self.temporary_root = TemporaryDirectory()
        self.addCleanup(self.temporary_root.cleanup)
        storage_patch = patch.object(private_document_storage, 'location', self.temporary_root.name)
        storage_patch.start()
        self.addCleanup(storage_patch.stop)

        self.admin_user = User.objects.create_superuser(
            username='review-admin', email='review-admin@example.com', password='test-password'
        )
        self.buyer = User.objects.create_user(username='review-buyer', email='buyer@example.com', password='test-password')
        self.silver = MembershipTier.objects.get(level='silver')
        self.silver.monthly_price_usdt = Decimal('12.50')
        self.silver.payment_url = 'https://pay.example/silver'
        self.silver.payment_network = 'TRC20'
        self.silver.save()
        self.purchase = PlanPurchase.objects.create(
            user=self.buyer, tier=self.silver, price_usdt=Decimal('12.50'),
            monthly_search_limit=self.silver.monthly_search_limit,
            monthly_download_limit=self.silver.monthly_download_limit,
            payment_url=self.silver.payment_url, payment_network='TRC20',
            status=PlanPurchase.SUBMITTED, txid='reviewtx001',
            receipt_image=PlanPurchaseTests.receipt(), submitted_at=timezone.now(),
        )
        self.review_url = reverse('accounts:purchase_review_detail', args=[self.purchase.pk])
        self.action_url = reverse('accounts:purchase_review_action', args=[self.purchase.pk])
        self.client.force_login(self.admin_user)

    def test_approval_activates_plan_and_records_reviewer(self):
        listing = self.client.get(reverse('accounts:purchase_review_list'))
        self.assertContains(listing, self.buyer.username)
        detail = self.client.get(self.review_url)
        self.assertContains(detail, self.purchase.txid)
        self.assertContains(detail, reverse('accounts:purchase_receipt', args=[self.purchase.pk]))

        response = self.client.post(self.action_url, {'decision': 'approved', 'note': 'Payment found on chain.'})
        self.assertRedirects(response, self.review_url)
        self.purchase.refresh_from_db()
        self.assertEqual(self.purchase.status, PlanPurchase.APPROVED)
        self.assertEqual(self.purchase.reviewed_by, self.admin_user)
        self.assertIsNotNone(self.purchase.reviewed_at)
        self.assertEqual(self.purchase.access_expires_at, one_month_later(self.purchase.reviewed_at))
        membership = UserMembership.objects.get(user=self.buyer)
        self.assertEqual(membership.tier_id, 'silver')
        self.assertEqual(membership.expires_at, self.purchase.access_expires_at)

        self.client.force_login(self.buyer)
        self.assertContains(self.client.get(reverse('accounts:profile')), 'Silver')
        self.assertContains(self.client.get(reverse('accounts:plan_purchase', args=[self.purchase.pk])), 'plan is active')

    def test_rejection_requires_reason_and_does_not_change_tier(self):
        invalid = self.client.post(self.action_url, {'decision': 'rejected', 'note': '  '})
        self.assertEqual(invalid.status_code, 400)
        self.assertContains(invalid, 'Enter a reason', status_code=400)
        self.purchase.refresh_from_db()
        self.assertEqual(self.purchase.status, PlanPurchase.SUBMITTED)

        response = self.client.post(self.action_url, {'decision': 'rejected', 'note': 'TXID does not match the receipt.'})
        self.assertRedirects(response, self.review_url)
        self.purchase.refresh_from_db()
        self.assertEqual(self.purchase.status, PlanPurchase.REJECTED)
        self.assertEqual(self.purchase.review_note, 'TXID does not match the receipt.')
        self.assertEqual(membership_for(self.buyer).tier_id, 'free')

        self.client.force_login(self.buyer)
        self.assertContains(self.client.get(reverse('accounts:plan_purchase', args=[self.purchase.pk])), self.purchase.review_note)
        self.client.post(reverse('accounts:start_plan_purchase', args=['silver']))
        self.assertEqual(PlanPurchase.objects.filter(user=self.buyer, tier=self.silver).count(), 2)

    def test_plan_edits_do_not_change_a_previous_purchase_or_active_allowance(self):
        original_limits = (self.purchase.monthly_search_limit, self.purchase.monthly_download_limit)
        self.silver.monthly_search_limit = 1
        self.silver.monthly_download_limit = 0
        self.silver.save(update_fields=['monthly_search_limit', 'monthly_download_limit'])

        self.client.post(self.action_url, {'decision': 'approved'})
        membership = UserMembership.objects.get(user=self.buyer)
        self.assertEqual((membership.monthly_search_limit, membership.monthly_download_limit), original_limits)
        self.client.force_login(self.buyer)
        profile = self.client.get(reverse('accounts:profile'))
        self.assertContains(profile, ' / {}'.format(original_limits[0]))
        self.assertContains(profile, ' / {}'.format(original_limits[1]))
        request = RequestFactory().post('/wire-transfer/')
        request.user = self.buyer
        self.assertTrue(consume_quota(request, 'searches'))
        self.assertTrue(consume_quota(request, 'downloads'))

        self.silver.monthly_search_limit = 0
        self.silver.monthly_download_limit = 0
        self.silver.save(update_fields=['monthly_search_limit', 'monthly_download_limit'])
        self.assertTrue(consume_quota(request, 'searches'))
        membership.refresh_from_db()
        self.assertEqual((membership.monthly_search_limit, membership.monthly_download_limit), original_limits)

        new_buyer = User.objects.create_user(username='new-quota-buyer', password='test-password')
        self.client.force_login(new_buyer)
        self.client.post(reverse('accounts:start_plan_purchase', args=['silver']))
        new_purchase = PlanPurchase.objects.get(user=new_buyer)
        self.assertEqual((new_purchase.monthly_search_limit, new_purchase.monthly_download_limit), (0, 0))

    def test_gold_purchase_keeps_its_limits_after_gold_defaults_change(self):
        gold = MembershipTier.objects.get(level='gold')
        original_limits = (gold.monthly_search_limit, gold.monthly_download_limit)
        gold_purchase = PlanPurchase.objects.create(
            user=self.buyer, tier=gold, price_usdt=Decimal('29.00'),
            monthly_search_limit=original_limits[0], monthly_download_limit=original_limits[1],
            payment_url='https://pay.example/gold', payment_network='TRC20',
            status=PlanPurchase.SUBMITTED, txid='goldreviewtx001',
            receipt_image=PlanPurchaseTests.receipt(), submitted_at=timezone.now(),
        )
        gold.monthly_search_limit = 1
        gold.monthly_download_limit = 0
        gold.save(update_fields=['monthly_search_limit', 'monthly_download_limit'])
        self.client.post(reverse('accounts:purchase_review_action', args=[gold_purchase.pk]), {'decision': 'approved'})
        membership = UserMembership.objects.get(user=self.buyer)
        self.assertEqual(membership.tier_id, 'gold')
        self.assertEqual((membership.monthly_search_limit, membership.monthly_download_limit), original_limits)

    def test_review_is_post_only_superuser_only_and_cannot_be_repeated(self):
        self.assertEqual(self.client.get(self.action_url).status_code, 405)
        staff = User.objects.create_user(username='review-staff', is_staff=True)
        self.client.force_login(staff)
        self.assertEqual(self.client.get(self.review_url).status_code, 403)
        self.assertEqual(self.client.post(self.action_url, {'decision': 'approved'}).status_code, 403)
        self.purchase.refresh_from_db()
        self.assertEqual(self.purchase.status, PlanPurchase.SUBMITTED)

        self.client.force_login(self.admin_user)
        self.client.post(self.action_url, {'decision': 'approved'})
        first_expiry = UserMembership.objects.get(user=self.buyer).expires_at
        self.client.post(self.action_url, {'decision': 'approved'})
        self.purchase.refresh_from_db()
        self.assertEqual(self.purchase.status, PlanPurchase.APPROVED)
        self.assertEqual(UserMembership.objects.get(user=self.buyer).expires_at, first_expiry)

    def test_renewal_extends_same_plan_and_expiry_returns_to_free(self):
        first_review = datetime(2026, 1, 31, 12, tzinfo=datetime_timezone.utc)
        with patch('accounts.purchase_review.timezone.now', return_value=first_review):
            self.client.post(self.action_url, {'decision': 'approved'})
        first_expiry = UserMembership.objects.get(user=self.buyer).expires_at
        self.assertEqual(first_expiry, datetime(2026, 2, 28, 12, tzinfo=datetime_timezone.utc))

        self.silver.monthly_search_limit = 1
        self.silver.monthly_download_limit = 0
        self.silver.save(update_fields=['monthly_search_limit', 'monthly_download_limit'])

        renewal = PlanPurchase.objects.create(
            user=self.buyer, tier=self.silver, price_usdt=Decimal('12.50'),
            monthly_search_limit=1, monthly_download_limit=0,
            payment_url=self.silver.payment_url, payment_network='TRC20',
            status=PlanPurchase.SUBMITTED, txid='reviewtx002',
            receipt_image=PlanPurchaseTests.receipt(), submitted_at=timezone.now(),
        )
        second_review = datetime(2026, 2, 10, 12, tzinfo=datetime_timezone.utc)
        with patch('accounts.purchase_review.timezone.now', return_value=second_review):
            self.client.post(reverse('accounts:purchase_review_action', args=[renewal.pk]), {'decision': 'approved'})
        membership = UserMembership.objects.get(user=self.buyer)
        self.assertEqual(membership.expires_at, datetime(2026, 3, 28, 12, tzinfo=datetime_timezone.utc))
        self.assertEqual((membership.monthly_search_limit, membership.monthly_download_limit), (self.purchase.monthly_search_limit, self.purchase.monthly_download_limit))

        with patch('accounts.quotas.timezone.now', return_value=datetime(2026, 3, 29, 12, tzinfo=datetime_timezone.utc)):
            self.assertEqual(membership_for(self.buyer).tier_id, 'free')
        membership.refresh_from_db()
        self.assertIsNone(membership.expires_at)


class MembershipQuotaTests(TestCase):
    def test_admin_sets_usdt_prices_for_paid_tiers(self):
        admin_user = User.objects.create_superuser(
            username='price-admin', email='price-admin@example.com', password='test-password'
        )
        self.client.force_login(admin_user)
        for level, price in (('silver', '12.50'), ('gold', '29.00')):
            tier = MembershipTier.objects.get(level=level)
            response = self.client.post(reverse('admin:accounts_membershiptier_change', args=[level]), {
                'monthly_search_limit': tier.monthly_search_limit,
                'monthly_download_limit': tier.monthly_download_limit,
                'monthly_price_usdt': price,
                'payment_url': f'https://pay.example/{level}',
                'payment_network': 'TRC20',
                '_save': 'Save',
            })
            self.assertEqual(response.status_code, 302)
            tier.refresh_from_db()
            self.assertEqual(tier.monthly_price_usdt, Decimal(price))
            self.assertEqual(tier.payment_url, f'https://pay.example/{level}')
            self.assertEqual(tier.payment_network, 'TRC20')

        pricing = self.client.get(reverse('pages:pricing'))
        self.assertContains(pricing, '12.50')
        self.assertContains(pricing, '29.00')
        self.assertContains(pricing, 'USDT')
        self.assertContains(pricing, 'Free')
        self.assertContains(pricing, 'Choose Silver')
        self.assertContains(pricing, 'Choose Gold')

        silver = MembershipTier.objects.get(level='silver')
        invalid = self.client.post(reverse('admin:accounts_membershiptier_change', args=['silver']), {
            'monthly_search_limit': silver.monthly_search_limit,
            'monthly_download_limit': silver.monthly_download_limit,
            'monthly_price_usdt': '-1.00',
            '_save': 'Save',
        })
        self.assertEqual(invalid.status_code, 200)
        silver.refresh_from_db()
        self.assertEqual(silver.monthly_price_usdt, Decimal('12.50'))

        free = MembershipTier.objects.get(level='free')
        self.client.post(reverse('admin:accounts_membershiptier_change', args=['free']), {
            'monthly_search_limit': free.monthly_search_limit,
            'monthly_download_limit': free.monthly_download_limit,
            'monthly_price_usdt': '99.00',
            '_save': 'Save',
        })
        free.refresh_from_db()
        self.assertEqual(free.monthly_price_usdt, Decimal('0.00'))

    def test_staff_without_superuser_status_still_has_plan_limits(self):
        staff = User.objects.create_user(username='limited-staff-quota', is_staff=True)
        request = RequestFactory().post('/wire-transfer/')
        request.user = staff
        free = MembershipTier.objects.get(level='free')
        free.monthly_search_limit = 0
        free.save()
        self.assertFalse(consume_quota(request, 'searches'))

    def test_admin_can_change_limits_and_assign_tier(self):
        admin_user = User.objects.create_superuser(
            username='quota-admin', email='admin@example.com', password='test-password'
        )
        member = User.objects.create_user(username='quota-member', email='member@example.com', password='test-password')
        self.client.force_login(admin_user)
        tier_url = reverse('admin:accounts_membershiptier_change', args=['silver'])
        response = self.client.post(tier_url, {
            'monthly_search_limit': 42,
            'monthly_download_limit': 7,
            '_save': 'Save',
        })
        self.assertEqual(response.status_code, 302)
        silver = MembershipTier.objects.get(level='silver')
        self.assertEqual((silver.monthly_search_limit, silver.monthly_download_limit), (42, 7))

        response = self.client.post(reverse('accounts:user_edit', args=[member.pk]), {
            'username': member.username,
            'email': member.email,
            'is_active': 'on',
            'membership_tier': 'silver',
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(UserMembership.objects.get(user=member).tier_id, 'silver')
        membership = UserMembership.objects.get(user=member)
        self.assertEqual((membership.monthly_search_limit, membership.monthly_download_limit), (42, 7))
        silver.monthly_search_limit = 1
        silver.monthly_download_limit = 0
        silver.save(update_fields=['monthly_search_limit', 'monthly_download_limit'])
        request = RequestFactory().post('/wire-transfer/')
        request.user = member
        self.assertTrue(consume_quota(request, 'downloads'))
        self.assertTrue(consume_quota(request, 'searches'))

    def test_tier_change_and_limit_edit_apply_immediately(self):
        user = User.objects.create_user(username='quota-user', password='test-password')
        request = RequestFactory().post('/wire-transfer/')
        request.user = user
        free = MembershipTier.objects.get(level='free')
        free.monthly_search_limit = 1
        free.save()
        self.assertTrue(consume_quota(request, 'searches'))
        self.assertFalse(consume_quota(request, 'searches'))

        free.monthly_search_limit = 2
        free.save()
        self.assertTrue(consume_quota(request, 'searches'))
        self.assertFalse(consume_quota(request, 'searches'))

        UserMembership.objects.filter(user=user).update(tier_id='silver')
        self.assertTrue(consume_quota(request, 'searches'))
        tier, usage = quota_status(request)
        self.assertEqual(tier.level, 'silver')
        self.assertEqual(usage.searches, 3)

    def test_downloads_are_independent_and_monthly_usage_resets(self):
        user = User.objects.create_user(username='downloads-user', password='test-password')
        request = RequestFactory().get('/download/')
        request.user = user
        free = MembershipTier.objects.get(level='free')
        free.monthly_download_limit = 1
        free.save()
        with patch('accounts.quotas.month_start', return_value=date(2026, 11, 1)):
            self.assertTrue(consume_quota(request, 'downloads'))
            self.assertFalse(consume_quota(request, 'downloads'))
            self.assertTrue(consume_quota(request, 'searches'))
        with patch('accounts.quotas.month_start', return_value=date(2026, 12, 1)):
            self.assertTrue(consume_quota(request, 'downloads'))
        self.assertEqual(MonthlyUsage.objects.filter(identity=f'user:{user.pk}').count(), 2)


class LoginRateLimitTests(TestCase):
    def setUp(self):
        self.url = reverse('accounts:login')
        self.credentials = {'username_or_email': 'testuser', 'password': 'StrongPass123!'}
        User.objects.create_user(username='testuser', password='StrongPass123!')

    @override_settings(LOGIN_RATE_LIMIT=2)
    def test_login_posts_are_limited_per_ip(self):
        client = Client()
        for _ in range(2):
            response = client.post(self.url, {'username_or_email': 'testuser', 'password': 'wrong'}, REMOTE_ADDR='198.51.100.10')
            self.assertEqual(response.status_code, 200)

        blocked = Client().post(self.url, self.credentials, REMOTE_ADDR='198.51.100.10')
        self.assertEqual(blocked.status_code, 429)
        self.assertIn('Retry-After', blocked)
        self.assertGreater(int(blocked['Retry-After']), 0)
        self.assertIn('no-store', blocked['Cache-Control'])
        self.assertContains(blocked, 'Too many sign-in attempts', status_code=429)
        self.assertFalse(blocked.wsgi_request.user.is_authenticated)
        self.assertEqual(LoginRateWindow.objects.get().attempts, 2)
        self.assertNotIn('198.51.100.10', LoginRateWindow.objects.get().lookup_key)

        other_ip = Client().post(self.url, self.credentials, REMOTE_ADDR='198.51.100.11')
        self.assertEqual(other_ip.status_code, 302)

    @override_settings(LOGIN_RATE_LIMIT=1, LOGIN_TRUSTED_PROXY_IPS={'10.0.0.1'})
    def test_forwarded_ip_only_counts_when_proxy_is_trusted(self):
        invalid = {'username_or_email': 'testuser', 'password': 'wrong'}
        first = Client().post(self.url, invalid, REMOTE_ADDR='10.0.0.1', HTTP_X_FORWARDED_FOR='198.51.100.20')
        self.assertEqual(first.status_code, 200)
        second = Client().post(self.url, invalid, REMOTE_ADDR='10.0.0.1', HTTP_X_FORWARDED_FOR='198.51.100.21')
        self.assertEqual(second.status_code, 200)
        blocked = Client().post(self.url, invalid, REMOTE_ADDR='10.0.0.1', HTTP_X_FORWARDED_FOR='198.51.100.20')
        self.assertEqual(blocked.status_code, 429)

        untrusted_first = Client().post(self.url, invalid, REMOTE_ADDR='203.0.113.1', HTTP_X_FORWARDED_FOR='198.51.100.30')
        self.assertEqual(untrusted_first.status_code, 200)
        untrusted_blocked = Client().post(self.url, invalid, REMOTE_ADDR='203.0.113.1', HTTP_X_FORWARDED_FOR='198.51.100.31')
        self.assertEqual(untrusted_blocked.status_code, 429)

    @override_settings(LOGIN_RATE_LIMIT=1, LOGIN_RATE_WINDOW_SECONDS=60)
    def test_limit_resets_in_next_window_and_get_remains_available(self):
        invalid = {'username_or_email': 'testuser', 'password': 'wrong'}
        start = datetime(2026, 1, 1, tzinfo=datetime_timezone.utc)
        with patch('accounts.rate_limit.timezone.now', return_value=start):
            self.assertEqual(Client().post(self.url, invalid).status_code, 200)
            self.assertEqual(Client().post(self.url, invalid).status_code, 429)
            self.assertEqual(Client().get(self.url).status_code, 200)
        with patch('accounts.rate_limit.timezone.now', return_value=start + timedelta(seconds=60)):
            self.assertEqual(Client().post(self.url, self.credentials).status_code, 302)


class AccountsAuthTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.password = "StrongPass123!"
        self.user = User.objects.create_user(
            username="testuser",
            email="testuser@example.com",
            password=self.password,
            first_name="Test",
            last_name="User"
        )
        self.staff_user = User.objects.create_user(
            username="staffuser",
            email="staff@example.com",
            password=self.password,
            is_staff=True
        )

    def test_login_with_username_success(self):
        response = self.client.post(reverse('accounts:login'), {
            'username_or_email': 'testuser',
            'password': self.password,
            'remember_me': True,
        }, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['user'].is_authenticated)
        self.assertEqual(response.context['user'].username, 'testuser')

    def test_login_with_email_success(self):
        response = self.client.post(reverse('accounts:login'), {
            'username_or_email': 'testuser@example.com',
            'password': self.password,
            'remember_me': False,
        }, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['user'].is_authenticated)

    def test_staff_without_transfer_permission_lands_on_home(self):
        response = self.client.post(reverse('accounts:login'), {
            'username_or_email': self.staff_user.username,
            'password': self.password,
        })
        self.assertRedirects(response, reverse('pages:home'))

    def test_login_invalid_password(self):
        response = self.client.post(reverse('accounts:login'), {
            'username_or_email': 'testuser',
            'password': 'WrongPassword123!',
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context['user'].is_authenticated)
        self.assertFormError(response.context['form'], None, "Invalid username/email or password.")

    def test_login_inactive_user(self):
        self.user.is_active = False
        self.user.save()
        response = self.client.post(reverse('accounts:login'), {
            'username_or_email': 'testuser',
            'password': self.password,
        })
        self.assertEqual(response.status_code, 200)
        self.assertFormError(response.context['form'], None, "This user account is inactive. Please contact an administrator.")

    def test_logout(self):
        self.client.login(username='testuser', password=self.password)
        response = self.client.post(reverse('accounts:logout'), follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context['user'].is_authenticated)

    def test_register_success(self):
        response = self.client.post(reverse('accounts:register'), {
            'username': 'newuser',
            'email': 'newuser@example.com',
            'first_name': 'New',
            'last_name': 'Person',
            'password': 'SecurePassword987!',
            'confirm_password': 'SecurePassword987!',
        }, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(User.objects.filter(username='newuser').exists())
        self.assertTrue(response.context['user'].is_authenticated)

    def test_register_with_next_redirect(self):
        response = self.client.post(reverse('accounts:register') + '?next=/wire-transfer/', {
            'username': 'wiretrackeruser',
            'email': 'wiretracker@example.com',
            'first_name': 'Wire',
            'last_name': 'User',
            'password': 'SecurePassword987!',
            'confirm_password': 'SecurePassword987!',
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, '/wire-transfer/')

    def test_register_password_mismatch(self):
        response = self.client.post(reverse('accounts:register'), {
            'username': 'newuser2',
            'email': 'newuser2@example.com',
            'password': 'SecurePassword987!',
            'confirm_password': 'DifferentPassword987!',
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(username='newuser2').exists())
        self.assertFormError(response.context['form'], 'confirm_password', "Passwords do not match.")

    def test_profile_view_update(self):
        self.client.login(username='testuser', password=self.password)
        response = self.client.get(reverse('accounts:profile'))
        self.assertEqual(response.status_code, 200)

        update_response = self.client.post(reverse('accounts:profile'), {
            'first_name': 'UpdatedFirst',
            'last_name': 'UpdatedLast',
            'email': 'updated@example.com',
        }, follow=True)
        self.assertEqual(update_response.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, 'UpdatedFirst')
        self.assertEqual(self.user.email, 'updated@example.com')

    def test_change_password(self):
        self.client.login(username='testuser', password=self.password)
        new_pass = "BrandNewPass999!"
        response = self.client.post(reverse('accounts:change_password'), {
            'current_password': self.password,
            'new_password': new_pass,
            'confirm_new_password': new_pass,
        }, follow=True)
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(new_pass))


class AccountsUserManagementTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.password = "AdminPass123!"
        self.superuser = User.objects.create_superuser(
            username="adminuser",
            email="admin@example.com",
            password=self.password,
        )
        self.regular_user = User.objects.create_user(
            username="regularuser",
            email="regular@example.com",
            password="RegularPass123!",
            first_name="Jane",
            last_name="Doe",
        )

    def test_user_list_requires_staff(self):
        # Anonymous user
        response = self.client.get(reverse('accounts:user_list'))
        self.assertNotEqual(response.status_code, 200)

        # Regular non-staff user
        self.client.login(username='regularuser', password='RegularPass123!')
        response = self.client.get(reverse('accounts:user_list'))
        self.assertNotEqual(response.status_code, 200)

        # Superuser
        self.client.login(username='adminuser', password=self.password)
        response = self.client.get(reverse('accounts:user_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'regularuser')

    def test_staff_cannot_manage_users_even_with_auth_permissions(self):
        staff = User.objects.create_user(
            username='limitedstaff', password='StaffPass123!', is_staff=True,
        )
        staff.user_permissions.add(*Permission.objects.filter(
            content_type__app_label='auth',
            codename__in=['add_user', 'change_user', 'delete_user', 'view_user'],
        ))
        self.client.force_login(staff)

        urls = [
            reverse('accounts:user_list'),
            reverse('accounts:user_create'),
            reverse('accounts:user_edit', args=[self.regular_user.pk]),
            reverse('accounts:user_password', args=[self.superuser.pk]),
            reverse('accounts:user_toggle_status', args=[self.regular_user.pk]),
            reverse('accounts:user_delete', args=[self.regular_user.pk]),
        ]
        for url in urls:
            with self.subTest(method='GET', url=url):
                self.assertEqual(self.client.get(url).status_code, 403)

        requests = [
            (urls[1], {
                'username': 'escalated', 'email': 'escalated@example.com',
                'password': 'EscalatedPass123!', 'confirm_password': 'EscalatedPass123!',
                'is_active': True, 'is_staff': True, 'is_superuser': True,
            }),
            (urls[2], {
                'username': self.regular_user.username,
                'email': self.regular_user.email,
                'is_active': True, 'is_staff': True, 'is_superuser': True,
            }),
            (urls[3], {
                'new_password': 'HijackedPass123!',
                'confirm_new_password': 'HijackedPass123!',
            }),
            (urls[4], {}),
            (urls[5], {}),
        ]
        for url, data in requests:
            with self.subTest(method='POST', url=url):
                self.assertEqual(self.client.post(url, data).status_code, 403)

        admin_urls = [
            reverse('admin:auth_user_changelist'),
            reverse('admin:auth_user_add'),
            reverse('admin:auth_user_change', args=[self.superuser.pk]),
        ]
        for url in admin_urls:
            with self.subTest(method='GET', url=url):
                self.assertEqual(self.client.get(url).status_code, 403)

        self.assertFalse(User.objects.filter(username='escalated').exists())
        self.regular_user.refresh_from_db()
        self.assertTrue(self.regular_user.is_active)
        self.assertFalse(self.regular_user.is_staff)
        self.assertFalse(self.regular_user.is_superuser)
        self.superuser.refresh_from_db()
        self.assertTrue(self.superuser.check_password(self.password))

    def test_user_list_search_and_filter(self):
        self.client.login(username='adminuser', password=self.password)

        # Search query
        response = self.client.get(reverse('accounts:user_list') + '?q=Jane')
        self.assertEqual(response.status_code, 200)
        user_list = list(response.context['users'])
        self.assertIn(self.regular_user, user_list)
        self.assertNotIn(self.superuser, user_list)

        # Role filter
        response = self.client.get(reverse('accounts:user_list') + '?role=superuser')
        self.assertEqual(response.status_code, 200)
        user_list = list(response.context['users'])
        self.assertIn(self.superuser, user_list)
        self.assertNotIn(self.regular_user, user_list)

    def test_admin_create_user(self):
        self.client.login(username='adminuser', password=self.password)
        response = self.client.post(reverse('accounts:user_create'), {
            'username': 'createduser',
            'email': 'created@example.com',
            'first_name': 'Created',
            'last_name': 'Account',
            'password': 'CreatedPass987!',
            'confirm_password': 'CreatedPass987!',
            'is_active': True,
            'is_staff': True,
        }, follow=True)
        self.assertEqual(response.status_code, 200)
        created = User.objects.get(username='createduser')
        self.assertTrue(created.is_staff)
        self.assertFalse(created.is_superuser)

    def test_admin_edit_user(self):
        self.client.login(username='adminuser', password=self.password)
        response = self.client.post(reverse('accounts:user_edit', args=[self.regular_user.pk]), {
            'username': 'regularuser',
            'email': 'newemail@example.com',
            'first_name': 'Janet',
            'last_name': 'Doe',
            'is_active': True,
            'is_staff': True,
        }, follow=True)
        self.assertEqual(response.status_code, 200)
        self.regular_user.refresh_from_db()
        self.assertEqual(self.regular_user.email, 'newemail@example.com')
        self.assertEqual(self.regular_user.first_name, 'Janet')
        self.assertTrue(self.regular_user.is_staff)

    def test_superuser_cannot_remove_own_staff_access(self):
        self.client.force_login(self.superuser)
        response = self.client.post(reverse('accounts:user_edit', args=[self.superuser.pk]), {
            'username': self.superuser.username,
            'email': self.superuser.email,
            'is_active': True,
            'is_superuser': True,
        })
        self.assertRedirects(response, reverse('accounts:user_edit', args=[self.superuser.pk]))
        self.superuser.refresh_from_db()
        self.assertTrue(self.superuser.is_staff)

    def test_admin_reset_user_password(self):
        self.client.login(username='adminuser', password=self.password)
        new_target_pass = "ResetPassByAdmin777!"
        response = self.client.post(reverse('accounts:user_password', args=[self.regular_user.pk]), {
            'new_password': new_target_pass,
            'confirm_new_password': new_target_pass,
        }, follow=True)
        self.assertEqual(response.status_code, 200)
        self.regular_user.refresh_from_db()
        self.assertTrue(self.regular_user.check_password(new_target_pass))

    def test_admin_toggle_user_status(self):
        self.client.login(username='adminuser', password=self.password)
        self.assertTrue(self.regular_user.is_active)
        toggle_url = reverse('accounts:user_toggle_status', args=[self.regular_user.pk])

        get_response = self.client.get(toggle_url)
        self.assertEqual(get_response.status_code, 405)
        self.regular_user.refresh_from_db()
        self.assertTrue(self.regular_user.is_active)

        response = self.client.post(toggle_url, follow=True)
        self.assertEqual(response.status_code, 200)
        self.regular_user.refresh_from_db()
        self.assertFalse(self.regular_user.is_active)

        # Cannot deactivate self
        response_self = self.client.post(reverse('accounts:user_toggle_status', args=[self.superuser.pk]), follow=True)
        self.assertEqual(response_self.status_code, 200)
        self.superuser.refresh_from_db()
        self.assertTrue(self.superuser.is_active)

    def test_status_toggle_requires_csrf_token(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.superuser)
        toggle_url = reverse('accounts:user_toggle_status', args=[self.regular_user.pk])
        page = client.get(reverse('accounts:user_list'))
        self.assertContains(page, f'action="{toggle_url}"')
        self.assertContains(page, 'name="csrfmiddlewaretoken"')

        self.assertEqual(client.post(toggle_url).status_code, 403)
        self.regular_user.refresh_from_db()
        self.assertTrue(self.regular_user.is_active)

        response = client.post(toggle_url, {
            'csrfmiddlewaretoken': client.cookies['csrftoken'].value,
        })
        self.assertEqual(response.status_code, 302)
        self.regular_user.refresh_from_db()
        self.assertFalse(self.regular_user.is_active)

    def test_admin_delete_user(self):
        self.client.login(username='adminuser', password=self.password)
        user_to_delete = User.objects.create_user(
            username="deleteme",
            password="DeleteMe123!"
        )

        # Confirmation page
        get_response = self.client.get(reverse('accounts:user_delete', args=[user_to_delete.pk]))
        self.assertEqual(get_response.status_code, 200)
        self.assertContains(get_response, 'deleteme')

        # Post delete
        post_response = self.client.post(reverse('accounts:user_delete', args=[user_to_delete.pk]), follow=True)
        self.assertEqual(post_response.status_code, 200)
        self.assertFalse(User.objects.filter(username="deleteme").exists())

        # Cannot delete self
        post_self = self.client.post(reverse('accounts:user_delete', args=[self.superuser.pk]), follow=True)
        self.assertTrue(User.objects.filter(username="adminuser").exists())


class MonthlyUsageAdminTests(TestCase):
    def test_admin_shows_user_email_and_keeps_visitor_identity(self):
        admin_user = User.objects.create_superuser(
            username='usage-admin', email='admin@example.com', password='test-password',
        )
        user = User.objects.create_user(
            username='usage-user', email='usage@example.com', password='test-password',
        )
        usage = MonthlyUsage.objects.create(identity=f'user:{user.pk}', month=date(2026, 11, 1))
        MonthlyUsage.objects.create(identity='ip:visitor-hash', month=date(2026, 11, 1))
        self.client.force_login(admin_user)

        changelist = self.client.get(reverse('admin:accounts_monthlyusage_changelist'))
        self.assertContains(changelist, 'usage@example.com')
        self.assertContains(changelist, 'ip:visitor-hash')
        self.assertNotContains(changelist, f'user:{user.pk}')

        detail = self.client.get(reverse('admin:accounts_monthlyusage_change', args=[usage.pk]))
        self.assertContains(detail, 'usage@example.com')
        self.assertNotContains(detail, f'user:{user.pk}')
