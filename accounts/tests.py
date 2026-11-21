from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from datetime import date
from unittest.mock import patch
from django.test import RequestFactory
from .models import MembershipTier, MonthlyUsage, UserMembership
from .quotas import consume_quota, quota_status

User = get_user_model()


class MembershipQuotaTests(TestCase):
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

    def test_login_invalid_password(self):
        response = self.client.post(reverse('accounts:login'), {
            'username_or_email': 'testuser',
            'password': 'WrongPassword123!',
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context['user'].is_authenticated)
        self.assertFormError(response, 'form', None, "Invalid username/email or password.")

    def test_login_inactive_user(self):
        self.user.is_active = False
        self.user.save()
        response = self.client.post(reverse('accounts:login'), {
            'username_or_email': 'testuser',
            'password': self.password,
        })
        self.assertEqual(response.status_code, 200)
        self.assertFormError(response, 'form', None, "This user account is inactive. Please contact an administrator.")

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
        self.assertFormError(response, 'form', 'confirm_password', "Passwords do not match.")

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

        # Toggle to inactive
        response = self.client.get(reverse('accounts:user_toggle_status', args=[self.regular_user.pk]), follow=True)
        self.assertEqual(response.status_code, 200)
        self.regular_user.refresh_from_db()
        self.assertFalse(self.regular_user.is_active)

        # Cannot deactivate self
        response_self = self.client.get(reverse('accounts:user_toggle_status', args=[self.superuser.pk]), follow=True)
        self.superuser.refresh_from_db()
        self.assertTrue(self.superuser.is_active)

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
