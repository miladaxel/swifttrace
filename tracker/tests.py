from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.contrib import admin
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory
from django.utils import timezone
from unittest.mock import patch
from types import SimpleNamespace
from tempfile import TemporaryDirectory
from pathlib import Path
from datetime import datetime, timedelta, timezone as datetime_timezone
from .admin import WireTransferAdmin
from .models import AccountSearchAttempt, ResultViewWindow, WireTransfer, TrackingStep, TransferSourceDocument, TransferStatusHistory, SearchRateWindow, TrackerSettings
from .services import MT103Parser
from .storage import private_document_storage
from .rate_limit import get_client_ip, cleanup_expired_search_windows
from tools.services import IBANValidatorService, SanctionsScreenerService
from accounts.models import MembershipTier, MonthlyUsage


class SwifttraceTrackerTests(TestCase):
    def setUp(self):
        self.client = Client()

    def test_mt103_parser(self):
        sample_mt103 = """{1:F01SVBLUS6SAXXX0000000000}{2:I103EBILAEADXXXXN}{3:{108:MT103}{121:c2b9a762-b91b-4df2-8e77-508b981f4f5a}}{4:
:20:SWIFT-USD-88910
:23B:CRED
:32A:261117USD125000,00
:50K:/US89SVBL9876543210
ALPHA GLOBAL TRADING LLC
:57A:EBILAEAD
:59:/AE070331234567890123456
PRIME HORIZON GENERAL TRADING
:71A:SHA
-}"""
        parsed = MT103Parser.parse(sample_mt103)
        self.assertEqual(parsed['uetr'], 'c2b9a762-b91b-4df2-8e77-508b981f4f5a')
        self.assertEqual(parsed['reference_number'], 'SWIFT-USD-88910')
        self.assertEqual(parsed['currency'], 'USD')
        self.assertEqual(parsed['amount'], 125000.0)
        self.assertEqual(parsed['charge_type'], 'SHA')

    def test_wire_transfer_view_get(self):
        response = self.client.get(reverse('tracker:wire_transfer'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Find Your Wire Transfer Record")
        self.assertContains(response, "Document Search")
        self.assertContains(response, "Where is the UETR?")
        self.assertContains(response, "Understanding a recorded status")
        self.assertContains(response, "Why was no document found?")
        self.assertContains(response, 'href="#search-help"')

    def test_search_guidance_on_invalid_or_missing_record(self):
        invalid = self.client.post(reverse('tracker:wire_transfer'), {
            'uetr': '12345678123412341234123456789abc', 'consent': 'on',
        })
        self.assertContains(invalid, 'five groups separated by hyphens')
        missing = self.client.post(reverse('tracker:wire_transfer'), {
            'uetr': 'a1f2a3b4-5c6d-7e8f-9a0b-1c2d3e4f5a6b', 'consent': 'on',
        })
        self.assertContains(missing, 'No published document matches')
        self.assertContains(missing, 'Check the search guide')
        self.assertContains(missing, 'A missing result does not prove the payment failed')

    def test_wire_tracking_post(self):
        transfer = WireTransfer.objects.create(
            uetr='e1f2a3b4-5c6d-7e8f-9a0b-1c2d3e4f5a6b',
            reference_number='REF-TEST-001',
            amount='50000.00', currency='USD', date_of_payment='2026-11-18',
            is_published=True,
        )
        response = self.client.post(reverse('tracker:wire_transfer'), {
            'uetr': 'e1f2a3b4-5c6d-7e8f-9a0b-1c2d3e4f5a6b',
            'reference': 'REF-TEST-001',
            'amount': '50000',
            'currency': 'USD',
            'date_of_payment': '2026-11-18',
            'consent': 'on'
        }, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Recorded Payment Stages")
        self.assertContains(response, "What do these statuses mean?")
        self.assertContains(response, "USD 50000.00")
        self.assertEqual(WireTransfer.objects.count(), 1)

    def test_search_does_not_create_or_expose_unpublished_records(self):
        unpublished = WireTransfer.objects.create(
            uetr='d1f2a3b4-5c6d-7e8f-9a0b-1c2d3e4f5a6b',
            reference_number='PRIVATE-001', amount='10.00', currency='USD',
            date_of_payment='2026-11-18',
        )
        response = self.client.post(reverse('tracker:wire_transfer'), {
            'uetr': unpublished.uetr, 'consent': 'on',
        })
        self.assertContains(response, 'No published document matches')
        self.assertEqual(WireTransfer.objects.count(), 1)
        self.assertEqual(self.client.get(reverse('tracker:tracking_result', args=[unpublished.pk])).status_code, 404)

        response = self.client.post(reverse('tracker:wire_transfer'), {
            'uetr': 'a1f2a3b4-5c6d-7e8f-9a0b-1c2d3e4f5a6b', 'consent': 'on',
        })
        self.assertContains(response, 'No published document matches')
        self.assertEqual(WireTransfer.objects.count(), 1)

    def test_reference_only_search_and_ambiguous_reference(self):
        first = WireTransfer.objects.create(
            reference_number='SAME-REF', amount='10.00', currency='USD',
            date_of_payment='2026-11-18', is_published=True,
        )
        WireTransfer.objects.create(
            reference_number='SAME-REF', amount='10.00', currency='EUR',
            date_of_payment='2026-11-18', is_published=True,
        )
        response = self.client.post(reverse('tracker:wire_transfer'), {
            'reference': 'SAME-REF', 'consent': 'on',
        })
        self.assertContains(response, 'enter the payment date and amount')
        response = self.client.post(reverse('tracker:wire_transfer'), {
            'reference': 'SAME-REF', 'date_of_payment': '2026-11-18',
            'amount': '10.00', 'consent': 'on',
        })
        self.assertContains(response, 'More than one document matches')
        response = self.client.post(reverse('tracker:wire_transfer'), {
            'reference': 'SAME-REF', 'date_of_payment': '2026-11-18',
            'amount': '10.00', 'currency': 'USD', 'consent': 'on',
        })
        self.assertRedirects(response, reverse('tracker:tracking_result', args=[first.pk]))

    def test_consent_and_direct_access(self):
        transfer = WireTransfer.objects.create(
            uetr='b1f2a3b4-5c6d-7e8f-9a0b-1c2d3e4f5a6b',
            amount='10.00', currency='USD', date_of_payment='2026-11-18',
            is_published=True,
        )
        url = reverse('tracker:tracking_result', args=[transfer.pk])
        self.assertEqual(self.client.get(url).status_code, 404)
        response = self.client.post(reverse('tracker:wire_transfer'), {'uetr': transfer.uetr})
        self.assertContains(response, 'This field is required')
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_iban_validator_service(self):
        # Valid UK IBAN
        valid_res = IBANValidatorService.validate("GB29NWBK60161331926819")
        self.assertTrue(valid_res['is_valid'])
        self.assertEqual(valid_res['country_code'], 'GB')

        # Invalid IBAN
        invalid_res = IBANValidatorService.validate("GB29NWBK60161331926818")
        self.assertFalse(invalid_res['is_valid'])

    def test_sanctions_screener_service(self):
        res = SanctionsScreenerService.screen("Sample Entity Alpha")
        self.assertEqual('SAMPLE MATCH', res['risk_level'])
        self.assertGreater(res['total_matches'], 0)
        self.assertEqual('fictional_sample', res['data_scope'])

        res_clean = SanctionsScreenerService.screen("Unlisted Example")
        self.assertEqual('NO SAMPLE MATCH', res_clean['risk_level'])

    def test_dashboard_view(self):
        self.assertEqual(self.client.get(reverse('dashboard:index')).status_code, 302)
        staff = get_user_model().objects.create_user(username='staff', password='test-password', is_staff=True)
        self.client.force_login(staff)
        self.assertEqual(self.client.get(reverse('dashboard:index')).status_code, 403)
        staff.user_permissions.add(Permission.objects.get(codename='view_wiretransfer'))
        response = self.client.get(reverse('dashboard:index'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Payment Records Dashboard")

    def test_dashboard_pages_filtered_records_and_preserves_search(self):
        staff = get_user_model().objects.create_user(username='records_staff', password='test-password', is_staff=True)
        staff.user_permissions.add(Permission.objects.get(codename='view_wiretransfer'))
        self.client.force_login(staff)
        WireTransfer.objects.bulk_create([
            WireTransfer(reference_number=f'BATCH-{index:02}', date_of_payment='2026-03-31',
                         amount=100, currency='USD', status='ACSP')
            for index in range(21)
        ])

        url = reverse('dashboard:index') + '?status=ACSP&q=BATCH'
        first_page = self.client.get(url)
        self.assertEqual(first_page.context['page_obj'].paginator.count, 21)
        self.assertEqual(len(first_page.context['transfers']), 20)
        self.assertContains(first_page, '?page=2&status=ACSP&q=BATCH')

        second_page = self.client.get(url + '&page=2')
        self.assertEqual(len(second_page.context['transfers']), 1)
        self.assertContains(second_page, 'BATCH-00')

    def test_pages_and_tools_views(self):
        pages_to_test = [
            (reverse('pages:home'), "Find a cross-border payment record"),
            (reverse('pages:for_business'), "A managed payment record portal"),
            (reverse('pages:about'), "About this project"),
            (reverse('pages:pricing'), "More room to follow every transfer."),
            (reverse('pages:scam_alert'), "Check payment claims with your bank"),
            (reverse('tools:correspondent_banks'), "Sample Currency Corridors"),
            (reverse('tools:arrival_estimator'), "Sample Transit Timing"),
            (reverse('tools:document_validator'), "MT103 Text Field Extractor"),
        ]
        for url, expected_text in pages_to_test:
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 200, f"Failed on URL: {url}")
            self.assertContains(resp, expected_text)

    def test_demo_tools_are_labelled_as_samples(self):
        response = self.client.post(reverse('tools:sanctions_screener'), {'query': 'Sample Entity Alpha'})
        self.assertContains(response, 'fictional names')
        self.assertContains(response, 'SAMPLE MATCH')
        self.assertNotContains(response, 'Passed Clean')
        response = self.client.get(reverse('tools:arrival_estimator'))
        self.assertNotContains(response, 'Dispatch Date')
        self.assertNotContains(response, 'Charge Model')

    def test_hsbc_imported_wire_and_search(self):
        # Create the HSBC wire in test db
        transfer = WireTransfer.objects.create(
            uetr='b4e791d2-a6f5-48c3-89d1-5c82e7a9b3f0',
            reference_number='HSBC-FT-20260331-59427',
            date_of_payment='2026-03-31',
            amount=79998940.00,
            currency='EUR',
            sender_name='EXCLUSIVE MEDIA LIMITED',
            beneficiary_name='SWIFT ASIA PACIFIC LIMITED',
            sender_bank_name='HSBC UK BANK PLC',
            beneficiary_bank_name='THE HONGKONG AND SHANGHAI BANKING CORPORATION LIMITED (HSBC)',
            status='ACCC',
            is_published=True,
        )

        staff = get_user_model().objects.create_user(username='staff', password='test-password', is_staff=True)
        staff.user_permissions.add(Permission.objects.get(codename='view_wiretransfer'))
        self.client.force_login(staff)

        # 1. Search in Dashboard by Sender
        resp_sender = self.client.get(reverse('dashboard:index') + '?q=EXCLUSIVE')
        self.assertContains(resp_sender, 'b4e791d2-a6f5-48c3-89d1-5c82e7a9b3f0')
        self.assertContains(resp_sender, 'EXCLUSIVE MEDIA LIMITED')

        # 2. Search in Dashboard by Beneficiary
        resp_bene = self.client.get(reverse('dashboard:index') + '?q=SWIFT+ASIA')
        self.assertContains(resp_bene, 'b4e791d2-a6f5-48c3-89d1-5c82e7a9b3f0')

        # 3. Search in Dashboard by Reference
        resp_ref = self.client.get(reverse('dashboard:index') + '?q=HSBC-FT-20260331-59427')
        self.assertContains(resp_ref, 'b4e791d2-a6f5-48c3-89d1-5c82e7a9b3f0')

        # 4. Search in Dashboard by UETR (uppercase or lowercase)
        resp_uetr = self.client.get(reverse('dashboard:index') + '?q=B4E791D2')
        self.assertContains(resp_uetr, 'HSBC-FT-20260331-59427')

        # 5. Track via Wire Transfer form
        self.client.logout()
        resp_track = self.client.post(reverse('tracker:wire_transfer'), {
            'uetr': 'B4E791D2-A6F5-48C3-89D1-5C82E7A9B3F0',
            'consent': 'on'
        }, follow=True)
        self.assertEqual(resp_track.status_code, 200)
        self.assertContains(resp_track, 'EXCLUSIVE MEDIA LIMITED')
        self.assertContains(resp_track, 'SWIFT ASIA PACIFIC LIMITED')

        # 6. Parse HSBC document layout
        sample_doc = """
        RCVD++ UNIQUE-END-TO-END-TRANSACTION-REFERENCE UETR:B4E791D2-A6F5-48C3-89D1-5C82E7A9B3F0
        F20: TRANSACTION REFERENCE 
        / HSBC-FT-20260331-59427
        F32A: VALUE DATE/CURRENCY/INTERBANK SETTLEDDATE 
        / DATE: 2026-03-31
        / CURRENCY: EUR
        F33B: CURRENCY/INSTRUCTED AMOUNT 
        / € 79,998,940.00
        F50K: ORDERING CUSTOMER NAME & ADDRESS 
        / EXCLUSIVE MEDIA LIMITED
        F59A: BENEFICIARY CUSTOMER NAME & ADD 
        / SWIFT ASIA PACIFIC LIMITED
        """
        parsed = MT103Parser.parse(sample_doc)
        self.assertEqual(parsed['uetr'], 'b4e791d2-a6f5-48c3-89d1-5c82e7a9b3f0')
        self.assertEqual(parsed['reference_number'], 'HSBC-FT-20260331-59427')
        self.assertEqual(parsed['amount'], 79998940.0)
        self.assertEqual(parsed['currency'], 'EUR')
        self.assertEqual(parsed['sender_name'], 'EXCLUSIVE MEDIA LIMITED')
        self.assertEqual(parsed['beneficiary_name'], 'SWIFT ASIA PACIFIC LIMITED')


class AdminDocumentWorkflowTests(TestCase):
    def setUp(self):
        self.admin_user = get_user_model().objects.create_superuser(
            username='document-admin', email='admin@example.test', password='test-password'
        )
        self.transfer = WireTransfer(
            reference_number='ADMIN-REF-001',
            date_of_payment='2026-11-18',
            amount='150.00',
            currency='USD',
            status='PDNG',
        )

    def test_publish_requires_source_and_observation_time(self):
        self.transfer.is_published = True
        with self.assertRaises(ValidationError) as raised:
            self.transfer.full_clean()
        self.assertIn('source_type', raised.exception.message_dict)
        self.assertIn('source_description', raised.exception.message_dict)
        self.assertIn('status_observed_at', raised.exception.message_dict)

        self.transfer.source_type = 'MT103'
        self.transfer.source_description = 'Confirmation supplied by the sending bank'
        self.transfer.status_observed_at = timezone.now()
        self.transfer.full_clean()

    def test_admin_records_status_changes_and_public_as_of_time(self):
        request = RequestFactory().post('/admin/tracker/wiretransfer/')
        request.user = self.admin_user
        model_admin = WireTransferAdmin(WireTransfer, admin.site)
        self.transfer.source_type = 'BANK'
        self.transfer.source_description = 'Sending bank confirmation'
        self.transfer.status_observed_at = timezone.now()
        self.transfer.is_published = True
        self.transfer.full_clean()
        model_admin.save_model(request, self.transfer, SimpleNamespace(cleaned_data={
            'status_update_note': 'Initial entry',
        }), change=False)

        self.transfer.status = 'ACSP'
        self.transfer.status_reason = 'Processing at intermediary bank'
        self.transfer.status_observed_at = timezone.now()
        model_admin.save_model(request, self.transfer, SimpleNamespace(cleaned_data={
            'status_update_note': 'New confirmation received',
        }), change=True)

        history = list(TransferStatusHistory.objects.filter(transfer=self.transfer))
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0].previous_status, 'PDNG')
        self.assertEqual(history[0].status, 'ACSP')
        self.assertEqual(history[0].changed_by, self.admin_user)
        self.assertEqual(history[0].note, 'New confirmation received')

        client = Client()
        response = client.post(reverse('tracker:wire_transfer'), {
            'reference': self.transfer.reference_number,
            'date_of_payment': '2026-11-18', 'amount': '150.00', 'consent': 'on',
        }, follow=True)
        self.assertContains(response, 'Status recorded as of')
        self.assertContains(response, 'Information source: Bank confirmation')
        self.assertContains(response, 'Recorded status updates')
        self.assertNotContains(response, 'New confirmation received')

    def test_source_file_is_private_and_admin_downloads_it(self):
        self.transfer.save()
        with TemporaryDirectory() as temporary_root, patch.object(private_document_storage, 'location', temporary_root):
            document = TransferSourceDocument(
                transfer=self.transfer,
                file=SimpleUploadedFile('bank-confirmation.pdf', b'%PDF-1.4\nsource document'),
                uploaded_by=self.admin_user,
            )
            document.full_clean()
            document.save()
            self.assertEqual(document.original_filename, 'bank-confirmation.pdf')
            self.assertTrue(Path(document.file.path).is_file())
            with self.assertRaises(ValueError):
                _ = document.file.url

            url = reverse('tracker:download_source_document', args=[document.pk])
            self.assertEqual(Client().get(url).status_code, 302)
            limited_staff = get_user_model().objects.create_user(
                username='limited-staff', password='test-password', is_staff=True
            )
            limited_client = Client()
            limited_client.force_login(limited_staff)
            self.assertEqual(limited_client.get(url).status_code, 403)
            client = Client()
            client.force_login(self.admin_user)
            response = client.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response['Cache-Control'], 'private, no-store')
            self.assertIn('attachment', response['Content-Disposition'])
            self.assertEqual(b''.join(response.streaming_content), b'%PDF-1.4\nsource document')
            response.close()

    def test_source_file_validation_rejects_wrong_type_and_oversize(self):
        self.transfer.save()
        wrong_type = TransferSourceDocument(
            transfer=self.transfer,
            file=SimpleUploadedFile('source.exe', b'not a document'),
        )
        with self.assertRaises(ValidationError):
            wrong_type.full_clean()

        oversized = TransferSourceDocument(
            transfer=self.transfer,
            file=SimpleUploadedFile('source.pdf', b'x' * (5 * 1024 * 1024 + 1)),
        )
        with self.assertRaises(ValidationError):
            oversized.full_clean()

    def test_admin_form_saves_published_record_and_source_file(self):
        client = Client()
        client.force_login(self.admin_user)
        observed = timezone.now()
        with TemporaryDirectory() as temporary_root, patch.object(private_document_storage, 'location', temporary_root):
            response = client.post(reverse('admin:tracker_wiretransfer_add'), {
                'uetr': '',
                'reference_number': 'ADMIN-FORM-001',
                'date_of_payment': '2026-11-18',
                'amount': '250.00',
                'currency': 'USD',
                'charge_type': 'SHA',
                'status': 'ACSP',
                'status_reason': 'Confirmed by bank',
                'status_observed_at_0': observed.strftime('%Y-%m-%d'),
                'status_observed_at_1': observed.strftime('%H:%M:%S'),
                'eta_delivery_0': '',
                'eta_delivery_1': '',
                'status_update_note': 'First confirmation',
                'source_type': 'BANK',
                'source_description': 'Bank payment confirmation',
                'sender_name': '', 'sender_account': '', 'sender_bank_name': '', 'sender_bank_bic': '',
                'beneficiary_name': '', 'beneficiary_account': '', 'beneficiary_bank_name': '', 'beneficiary_bank_bic': '',
                'is_published': 'on',
                'source_documents-TOTAL_FORMS': '1',
                'source_documents-INITIAL_FORMS': '0',
                'source_documents-MIN_NUM_FORMS': '0',
                'source_documents-MAX_NUM_FORMS': '1000',
                'source_documents-0-file': SimpleUploadedFile('source.pdf', b'%PDF-1.4\nconfirmation'),
                'source_documents-0-description': 'Original bank confirmation',
                'steps-TOTAL_FORMS': '1',
                'steps-INITIAL_FORMS': '0',
                'steps-MIN_NUM_FORMS': '0',
                'steps-MAX_NUM_FORMS': '1000',
                'steps-0-step_order': '1',
                'steps-0-bank_name': 'Sending Bank',
                'steps-0-bank_bic': 'BANKUS33',
                'steps-0-location': 'New York, US',
                'steps-0-role': 'Ordering Institution',
                'steps-0-status_label': 'Processed',
                'steps-0-status_code': 'ACSP',
                'steps-0-fee_deducted': '0.00',
                'steps-0-timestamp_0': observed.strftime('%Y-%m-%d'),
                'steps-0-timestamp_1': observed.strftime('%H:%M:%S'),
                'status_history-TOTAL_FORMS': '0',
                'status_history-INITIAL_FORMS': '0',
                'status_history-MIN_NUM_FORMS': '0',
                'status_history-MAX_NUM_FORMS': '0',
                '_save': 'Save',
            })
            if response.status_code == 200:
                errors = [response.context['adminform'].form.errors]
                errors.extend(formset.formset.errors for formset in response.context['inline_admin_formsets'])
                self.fail(f'Admin form did not save: {errors}')
            self.assertEqual(response.status_code, 302)
            record = WireTransfer.objects.get(reference_number='ADMIN-FORM-001')
            self.assertTrue(record.is_published)
            self.assertEqual(record.source_documents.count(), 1)
            self.assertEqual(record.source_documents.get().uploaded_by, self.admin_user)
            self.assertEqual(record.status_history.count(), 1)
            self.assertEqual(record.steps.count(), 1)

    def test_admin_add_page_shows_source_and_file_fields(self):
        client = Client()
        client.force_login(self.admin_user)
        response = client.get(reverse('admin:tracker_wiretransfer_add'))
        self.assertContains(response, 'source_type')
        self.assertContains(response, 'source_description')
        self.assertContains(response, 'status_observed_at')
        self.assertContains(response, 'source_documents-0-file')


class PublicSearchPrivacyTests(TestCase):
    def setUp(self):
        self.transfer = WireTransfer.objects.create(
            uetr='e1f2a3b4-5c6d-7e8f-9a0b-1c2d3e4f5a6b',
            reference_number='PRIVATE-REF',
            date_of_payment='2026-11-18', amount='150.00', currency='USD',
            sender_account='GB29NWBK60161331926819',
            beneficiary_account='AE070331234567890123456',
            status_reason='Private note: GB29NWBK60161331926819',
            is_published=True,
        )

    def test_public_result_masks_accounts_and_internal_notes(self):
        TrackingStep.objects.create(
            transfer=self.transfer, step_order=1, bank_name='Sending Bank',
            bank_bic='BANKUS33', location='New York, US', role='Sender',
            status_label='Processed', status_code='ACSP', timestamp=timezone.now(),
            details='Private note: AE070331234567890123456',
        )
        client = Client()
        response = client.post(reverse('tracker:wire_transfer'), {
            'uetr': self.transfer.uetr, 'consent': 'on',
        }, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'GB29NWBK60161331926819')
        self.assertNotContains(response, 'AE070331234567890123456')
        self.assertContains(response, '••••6819')
        self.assertContains(response, '••••3456')

        admin_user = get_user_model().objects.create_superuser(
            username='privacy-admin', email='admin@example.test', password='test-password'
        )
        client.force_login(admin_user)
        staff_response = client.get(reverse('tracker:tracking_result', args=[self.transfer.pk]))
        self.assertContains(staff_response, 'GB29NWBK60161331926819')

        limited_staff = get_user_model().objects.create_user(
            username='no-record-permission', password='test-password', is_staff=True
        )
        client.force_login(limited_staff)
        self.assertEqual(client.get(reverse('tracker:tracking_result', args=[self.transfer.pk])).status_code, 404)

    def test_result_access_expires_and_is_not_cached_or_indexed(self):
        client = Client()
        response = client.post(reverse('tracker:wire_transfer'), {
            'uetr': self.transfer.uetr, 'consent': 'on',
        })
        self.assertEqual(response.status_code, 302)
        result_url = reverse('tracker:tracking_result', args=[self.transfer.pk])
        result = client.get(result_url)
        self.assertEqual(result.status_code, 200)
        self.assertIn('no-store', result['Cache-Control'])
        self.assertEqual(result['X-Robots-Tag'], 'noindex, nofollow')
        session = client.session
        session['found_transfer_expires_at'] = 0
        session.save()
        self.assertEqual(client.get(result_url).status_code, 404)

    def test_result_page_is_limited_to_30_views_per_successful_search(self):
        client = Client()
        search_url = reverse('tracker:wire_transfer')
        query = {'uetr': self.transfer.uetr, 'consent': 'on'}
        self.assertEqual(client.post(search_url, query).status_code, 302)
        result_url = reverse('tracker:tracking_result', args=[self.transfer.pk])
        self.assertEqual(Client().get(result_url).status_code, 404)

        for _ in range(30):
            self.assertEqual(client.get(result_url).status_code, 200)
        grant = ResultViewWindow.objects.get()
        self.assertEqual(grant.views, 30)
        blocked = client.get(result_url)
        self.assertContains(blocked, 'Result view limit reached', status_code=429)
        self.assertIn('no-store', blocked['Cache-Control'])
        grant.refresh_from_db()
        self.assertEqual(grant.views, 30)
        self.assertEqual(MonthlyUsage.objects.get().searches, 1)

        self.assertEqual(client.post(search_url, query).status_code, 302)
        self.assertEqual(client.get(result_url).status_code, 200)
        self.assertEqual(MonthlyUsage.objects.get().searches, 2)
        self.assertEqual(ResultViewWindow.objects.count(), 2)

    @override_settings(WIRE_SEARCH_LIMIT=2)
    def test_search_rate_limit_counts_attempts_without_storing_ip(self):
        client = Client()
        query = {'uetr': 'a1f2a3b4-5c6d-7e8f-9a0b-1c2d3e4f5a6b', 'consent': 'on'}
        self.assertEqual(client.post(reverse('tracker:wire_transfer'), query).status_code, 200)
        self.assertEqual(client.post(reverse('tracker:wire_transfer'), query).status_code, 200)
        blocked = client.post(reverse('tracker:wire_transfer'), query)
        self.assertEqual(blocked.status_code, 429)
        self.assertIn('Retry-After', blocked)
        self.assertContains(blocked, 'Too many searches', status_code=429)
        counter = SearchRateWindow.objects.get()
        self.assertEqual(counter.attempts, 2)
        self.assertNotIn('127.0.0.1', counter.lookup_key)

    @override_settings(WIRE_TRUSTED_PROXY_IPS={'10.0.0.1'})
    def test_forwarded_ip_is_used_only_for_trusted_proxy(self):
        request = RequestFactory().post(
            '/wire-transfer/', REMOTE_ADDR='10.0.0.1',
            HTTP_X_FORWARDED_FOR='198.51.100.2, 203.0.113.9',
        )
        self.assertEqual(get_client_ip(request), '203.0.113.9')
        request.META['REMOTE_ADDR'] = '198.51.100.10'
        self.assertEqual(get_client_ip(request), '198.51.100.10')

    def test_parse_mt103_api_file_upload_and_size_limit(self):
        client = Client()
        url = reverse('tracker:parse_mt103_api')

        # 1. Valid small document upload
        valid_content = b"{1:F01TEST}{4:\n:20:REF-123\n-}"
        small_file = SimpleUploadedFile('mt103.txt', valid_content, content_type='text/plain')
        response = client.post(url, {'document': small_file})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['success'])
        self.assertEqual(response.json()['data']['reference_number'], 'REF-123')

        # 2. Oversized file upload (> 2MB)
        oversized_content = b'x' * (2 * 1024 * 1024 + 1)
        large_file = SimpleUploadedFile('large.txt', oversized_content, content_type='text/plain')
        response_oversized = client.post(url, {'document': large_file})
        self.assertEqual(response_oversized.status_code, 400)
        self.assertFalse(response_oversized.json()['success'])
        self.assertIn('2 MB or smaller', response_oversized.json()['error'])

        for payload in ('[]', '{"raw_text": 42}', '{"raw_text": ""}'):
            malformed = client.post(url, data=payload, content_type='application/json')
            self.assertEqual(malformed.status_code, 400)
        long_text = client.post(url, data='{"raw_text": "' + 'x' * (128 * 1024 + 1) + '"}',
                                content_type='application/json')
        self.assertEqual(long_text.status_code, 400)
        self.assertIn('128 KB or smaller', long_text.json()['error'])
        too_large_body = client.post(url, data='{"raw_text": "' + 'x' * (160 * 1024) + '"}',
                                     content_type='application/json')
        self.assertEqual(too_large_body.status_code, 413)

    def test_cleanup_expired_search_windows(self):
        from datetime import timedelta
        now = timezone.now()
        expired = SearchRateWindow.objects.create(
            lookup_key='expired-key',
            window_start=now - timedelta(days=2),
            attempts=5,
        )
        active = SearchRateWindow.objects.create(
            lookup_key='active-key',
            window_start=now,
            attempts=1,
        )
        cleanup_expired_search_windows(now)
        self.assertFalse(SearchRateWindow.objects.filter(pk=expired.pk).exists())
        self.assertTrue(SearchRateWindow.objects.filter(pk=active.pk).exists())

    def test_default_tracker_settings_is_login_not_required(self):
        settings_obj = TrackerSettings.get_settings()
        self.assertFalse(settings_obj.require_login)
        self.assertFalse(TrackerSettings.is_login_required())

        # Anonymous user should have full access by default
        response = self.client.get(reverse('tracker:wire_transfer'))
        self.assertEqual(response.status_code, 200)

    def test_wire_transfer_access_when_login_required(self):
        settings_obj = TrackerSettings.get_settings()
        settings_obj.require_login = True
        settings_obj.save()

        # Anonymous user attempting to GET wire_transfer should be redirected to login
        response = self.client.get(reverse('tracker:wire_transfer'))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('accounts:login'), response.url)
        self.assertIn('next=/wire-transfer/', response.url)

        # Anonymous user attempting to POST to wire_transfer should also be redirected to login
        post_response = self.client.post(reverse('tracker:wire_transfer'), {
            'uetr': 'c2b9a762-b91b-4df2-8e77-508b981f4f5a',
        })
        self.assertEqual(post_response.status_code, 302)
        self.assertIn(reverse('accounts:login'), post_response.url)

        # Anonymous user attempting to view tracking_result should also be redirected to login
        track_response = self.client.get(reverse('tracker:tracking_result', kwargs={'transfer_id': 999}))
        self.assertEqual(track_response.status_code, 302)
        self.assertIn(reverse('accounts:login'), track_response.url)

        # Authenticated user should have access
        User = get_user_model()
        user = User.objects.create_user(username='regularuser', password='Password123!')
        self.client.login(username='regularuser', password='Password123!')

        auth_response = self.client.get(reverse('tracker:wire_transfer'))
        self.assertEqual(auth_response.status_code, 200)

    def test_singleton_tracker_settings(self):
        s1 = TrackerSettings.get_settings()
        s2 = TrackerSettings(pk=2, require_login=True)
        s2.save()  # Should force pk=1
        self.assertEqual(s2.pk, 1)
        self.assertEqual(TrackerSettings.objects.count(), 1)

    def test_toggle_tracker_login_requirement_endpoint(self):
        User = get_user_model()
        staff_user = User.objects.create_user(username='staffadmin', password='Password123!', is_staff=True)
        view_perm = Permission.objects.get(codename='view_wiretransfer')
        staff_user.user_permissions.add(view_perm)
        regular_user = User.objects.create_user(username='normaluser', password='Password123!')

        url = reverse('tracker:toggle_login_requirement')

        # 1. Anonymous user cannot toggle
        anon_res = self.client.post(url)
        self.assertEqual(anon_res.status_code, 302)

        # 2. Regular (non-staff) user cannot toggle
        self.client.login(username='normaluser', password='Password123!')
        reg_res = self.client.post(url)
        self.assertEqual(reg_res.status_code, 302)
        self.assertIn(reverse('admin:login'), reg_res.url)

        # 3. Staff user can toggle
        self.client.login(username='staffadmin', password='Password123!')
        self.assertFalse(TrackerSettings.is_login_required())

        toggle_res1 = self.client.post(url, follow=True)
        self.assertEqual(toggle_res1.status_code, 200)
        self.assertTrue(TrackerSettings.is_login_required())

        # Toggle back
        toggle_res2 = self.client.post(url, follow=True)
        self.assertEqual(toggle_res2.status_code, 200)
        self.assertFalse(TrackerSettings.is_login_required())

    def test_admin_site_tracker_settings_registration(self):
        from .admin import TrackerSettingsAdmin
        self.assertIn(TrackerSettings, admin.site._registry)
        model_admin = admin.site._registry[TrackerSettings]
        self.assertIsInstance(model_admin, TrackerSettingsAdmin)
        self.assertIn('require_login', model_admin.list_editable)
        self.assertFalse(model_admin.has_delete_permission(None))

    def test_download_source_document_and_statement_after_search(self):
        self.transfer.is_published = True
        self.transfer.source_type = 'MT103'
        self.transfer.source_description = 'Bank MT103 copy'
        self.transfer.status_observed_at = timezone.now()
        self.transfer.save()

        with TemporaryDirectory() as temporary_root, patch.object(private_document_storage, 'location', temporary_root):
            doc = TransferSourceDocument.objects.create(
                transfer=self.transfer,
                file=SimpleUploadedFile('swift-confirmation.pdf', b'%PDF-1.4 sample file content'),
                original_filename='swift-confirmation.pdf',
                description='Official Bank Swift MT103 Slip',
            )

            # Search as visitor
            search_client = Client()
            search_res = search_client.post(reverse('tracker:wire_transfer'), {
                'uetr': self.transfer.uetr,
                'consent': 'on',
            })
            self.assertEqual(search_res.status_code, 302)
            self.assertEqual(search_res.url, reverse('tracker:tracking_result', kwargs={'transfer_id': self.transfer.pk}))

            # Result page should render document links
            result_res = search_client.get(search_res.url)
            self.assertEqual(result_res.status_code, 200)
            self.assertContains(result_res, 'swift-confirmation.pdf')
            self.assertContains(result_res, reverse('tracker:download_source_document', kwargs={'document_id': doc.pk}))
            self.assertContains(result_res, reverse('tracker:download_transfer_statement', kwargs={'transfer_id': self.transfer.pk}))

            # Download attached source document
            doc_download = search_client.get(reverse('tracker:download_source_document', kwargs={'document_id': doc.pk}))
            self.assertEqual(doc_download.status_code, 200)
            self.assertEqual(doc_download['Content-Disposition'], 'attachment; filename="swift-confirmation.pdf"')
            self.assertEqual(b''.join(doc_download.streaming_content), b'%PDF-1.4 sample file content')
            doc_download.close()

            # Download statement
            statement_download = search_client.get(reverse('tracker:download_transfer_statement', kwargs={'transfer_id': self.transfer.pk}))
            self.assertEqual(statement_download.status_code, 200)
            self.assertIn('attachment; filename="wire-statement-', statement_download['Content-Disposition'])
            self.assertIn(self.transfer.uetr, statement_download.content.decode('utf-8'))

    def test_download_document_without_search_denied(self):
        self.transfer.is_published = True
        self.transfer.source_type = 'MT103'
        self.transfer.source_description = 'Bank MT103 copy'
        self.transfer.status_observed_at = timezone.now()
        self.transfer.save()

        with TemporaryDirectory() as temporary_root, patch.object(private_document_storage, 'location', temporary_root):
            doc = TransferSourceDocument.objects.create(
                transfer=self.transfer,
                file=SimpleUploadedFile('secret.pdf', b'secret'),
                original_filename='secret.pdf',
            )

            # Client without search session
            unauth_client = Client()

            # Statement download without search session should raise 404 (or 302 to login)
            stat_res = unauth_client.get(reverse('tracker:download_transfer_statement', kwargs={'transfer_id': self.transfer.pk}))
            self.assertEqual(stat_res.status_code, 302)

            # Source doc download without search session should redirect to login
            doc_res = unauth_client.get(reverse('tracker:download_source_document', kwargs={'document_id': doc.pk}))
            self.assertEqual(doc_res.status_code, 302)

    def test_download_document_when_login_required(self):
        settings_obj = TrackerSettings.get_settings()
        settings_obj.require_login = True
        settings_obj.save()

        self.transfer.is_published = True
        self.transfer.source_type = 'MT103'
        self.transfer.source_description = 'Bank MT103 copy'
        self.transfer.status_observed_at = timezone.now()
        self.transfer.save()

        with TemporaryDirectory() as temporary_root, patch.object(private_document_storage, 'location', temporary_root):
            doc = TransferSourceDocument.objects.create(
                transfer=self.transfer,
                file=SimpleUploadedFile('test.pdf', b'sample'),
                original_filename='test.pdf',
            )

            # 1. Anonymous user with simulated search session still blocked when login is required
            session_client = Client()
            session = session_client.session
            session['found_transfer_id'] = self.transfer.pk
            session['found_transfer_expires_at'] = int(timezone.now().timestamp()) + 900
            session.save()

            res1 = session_client.get(reverse('tracker:download_source_document', kwargs={'document_id': doc.pk}))
            self.assertEqual(res1.status_code, 302)
            self.assertIn(reverse('accounts:login'), res1.url)

            # 2. Authenticated user with search session allowed
            User = get_user_model()
            user = User.objects.create_user(username='docdownloader', password='Password123!')
            session_client.login(username='docdownloader', password='Password123!')

            res2 = session_client.get(reverse('tracker:download_source_document', kwargs={'document_id': doc.pk}))
            self.assertEqual(res2.status_code, 200)
            res2.close()


class MembershipViewTests(TestCase):
    @override_settings(ACCOUNT_SEARCH_RATE_LIMIT=5, ACCOUNT_SEARCH_IP_RATE_LIMIT=2)
    def test_new_accounts_cannot_bypass_the_shared_ip_search_limit(self):
        first = get_user_model().objects.create_user(username='ip-search-one', password='test-password')
        second = get_user_model().objects.create_user(username='ip-search-two', password='test-password')
        first_client = Client()
        second_client = Client()
        first_client.force_login(first)
        second_client.force_login(second)
        search_url = reverse('tracker:wire_transfer')
        missing = {'uetr': 'd1f2a3b4-5c6d-7e8f-9a0b-1c2d3e4f5a6b', 'consent': 'on'}
        self.assertEqual(first_client.post(search_url, missing, REMOTE_ADDR='198.51.100.10').status_code, 200)
        self.assertEqual(second_client.post(search_url, missing, REMOTE_ADDR='198.51.100.10').status_code, 200)
        blocked = second_client.post(search_url, missing, REMOTE_ADDR='198.51.100.10')
        self.assertEqual(blocked.status_code, 429)
        self.assertGreater(int(blocked['Retry-After']), 0)
        self.assertEqual(second_client.post(search_url, missing, REMOTE_ADDR='198.51.100.11').status_code, 200)
        self.assertEqual(AccountSearchAttempt.objects.filter(user=second).count(), 2)
        self.assertFalse(MonthlyUsage.objects.exists())

    @override_settings(ACCOUNT_SEARCH_RATE_LIMIT=2, ACCOUNT_SEARCH_WINDOW_SECONDS=3600)
    def test_account_search_requests_are_limited_across_ips_for_a_rolling_hour(self):
        user = get_user_model().objects.create_user(username='hourly-search-user', password='test-password')
        other = get_user_model().objects.create_user(username='other-search-user', password='test-password')
        transfer = WireTransfer.objects.create(
            uetr='e1f2a3b4-5c6d-7e8f-9a0b-1c2d3e4f5a6b',
            date_of_payment=timezone.localdate(), amount='100.00', currency='USD', is_published=True,
        )
        self.client.force_login(user)
        search_url = reverse('tracker:wire_transfer')
        missing = {'uetr': 'd1f2a3b4-5c6d-7e8f-9a0b-1c2d3e4f5a6b', 'consent': 'on'}
        found = {'uetr': transfer.uetr, 'consent': 'on'}
        start = datetime(2026, 11, 27, 12, tzinfo=datetime_timezone.utc)
        with patch('tracker.rate_limit.timezone.now', return_value=start):
            self.assertEqual(self.client.post(search_url, missing, REMOTE_ADDR='198.51.100.1').status_code, 200)
            self.assertEqual(self.client.post(search_url, {'uetr': 'invalid', 'consent': 'on'}, REMOTE_ADDR='198.51.100.2').status_code, 200)
            blocked = self.client.post(search_url, found, REMOTE_ADDR='198.51.100.3')
            self.assertEqual(blocked.status_code, 429)
            self.assertEqual(blocked['Retry-After'], '3600')
            self.assertEqual(AccountSearchAttempt.objects.filter(user=user).count(), 2)
            self.assertFalse(MonthlyUsage.objects.filter(identity=f'user:{user.pk}').exists())

            other_client = Client()
            other_client.force_login(other)
            self.assertEqual(other_client.post(search_url, found, REMOTE_ADDR='198.51.100.1').status_code, 302)

        with patch('tracker.rate_limit.timezone.now', return_value=start + timedelta(seconds=3599)):
            blocked = self.client.post(search_url, found)
            self.assertEqual(blocked.status_code, 429)
            self.assertEqual(blocked['Retry-After'], '1')
        with patch('tracker.rate_limit.timezone.now', return_value=start + timedelta(seconds=3600)):
            self.assertEqual(self.client.post(search_url, found).status_code, 302)
        self.assertEqual(MonthlyUsage.objects.get(identity=f'user:{user.pk}').searches, 1)

    def test_only_unique_published_matches_consume_monthly_search_quota(self):
        user = get_user_model().objects.create_user(username='search-quota-member', password='test-password')
        self.client.force_login(user)
        free = MembershipTier.objects.get(level='free')
        free.monthly_search_limit = 1
        free.save(update_fields=['monthly_search_limit'])
        first = WireTransfer.objects.create(
            uetr='a1f2a3b4-5c6d-7e8f-9a0b-1c2d3e4f5a6b', reference_number='SHARED-REF',
            date_of_payment=timezone.localdate(), amount='100.00', currency='USD', is_published=True,
        )
        second = WireTransfer.objects.create(
            uetr='b1f2a3b4-5c6d-7e8f-9a0b-1c2d3e4f5a6b', reference_number='SHARED-REF',
            date_of_payment=timezone.localdate(), amount='100.00', currency='EUR', is_published=True,
        )
        unpublished = WireTransfer.objects.create(
            uetr='c1f2a3b4-5c6d-7e8f-9a0b-1c2d3e4f5a6b',
            date_of_payment=timezone.localdate(), amount='100.00', currency='USD', is_published=False,
        )
        search_url = reverse('tracker:wire_transfer')
        missing = {'uetr': 'd1f2a3b4-5c6d-7e8f-9a0b-1c2d3e4f5a6b', 'consent': 'on'}
        invalid = {'uetr': 'invalid', 'consent': 'on'}
        ambiguous = {
            'reference': 'SHARED-REF', 'date_of_payment': str(timezone.localdate()),
            'amount': '100.00', 'consent': 'on',
        }
        for query in (invalid, missing, ambiguous, {'uetr': unpublished.uetr, 'consent': 'on'}):
            self.assertEqual(self.client.post(search_url, query).status_code, 200)
        self.assertFalse(MonthlyUsage.objects.filter(identity=f'user:{user.pk}').exists())

        self.assertEqual(self.client.post(search_url, {'uetr': first.uetr, 'consent': 'on'}).status_code, 302)
        usage = MonthlyUsage.objects.get(identity=f'user:{user.pk}')
        self.assertEqual(usage.searches, 1)
        self.assertEqual(self.client.post(search_url, missing).status_code, 200)
        blocked = self.client.post(search_url, {'uetr': second.uetr, 'consent': 'on'})
        self.assertEqual(blocked.status_code, 429)
        self.assertEqual(self.client.get(reverse('tracker:tracking_result', args=[second.pk])).status_code, 404)
        usage.refresh_from_db()
        self.assertEqual(usage.searches, 1)

    def test_superuser_is_exempt_from_membership_limits(self):
        admin_user = get_user_model().objects.create_superuser(
            username='quota-admin-view', email='quota-admin@example.com', password='test-password'
        )
        self.client.force_login(admin_user)
        free = MembershipTier.objects.get(level='free')
        free.monthly_search_limit = 1
        free.monthly_download_limit = 0
        free.save()
        transfer = WireTransfer.objects.create(
            uetr='87e98b4c-6d01-43b6-a693-431902c36026',
            date_of_payment=timezone.localdate(), amount='100.00', currency='USD',
        )
        search_url = reverse('tracker:wire_transfer')
        query = {'uetr': transfer.uetr, 'consent': 'on'}
        self.assertEqual(self.client.post(search_url, query).status_code, 200)
        self.assertEqual(self.client.post(search_url, query).status_code, 200)
        statement_url = reverse('tracker:download_transfer_statement', args=[transfer.pk])
        self.assertEqual(self.client.get(statement_url).status_code, 200)
        self.assertFalse(MonthlyUsage.objects.filter(identity=f'user:{admin_user.pk}').exists())

    def test_search_and_statement_enforce_current_tier_limits(self):
        user = get_user_model().objects.create_user(username='member', password='test-password')
        self.client.force_login(user)
        free = MembershipTier.objects.get(level='free')
        free.monthly_search_limit = 1
        free.monthly_download_limit = 1
        free.save()
        transfer = WireTransfer.objects.create(
            uetr='c2b9a762-b91b-4df2-8e77-508b981f4f5a',
            date_of_payment=timezone.localdate(), amount='100.00', currency='USD',
            is_published=True, source_type='MT103', source_description='Test document',
            status_observed_at=timezone.now(),
        )
        query = {'uetr': transfer.uetr, 'consent': 'on'}
        search_url = reverse('tracker:wire_transfer')
        self.assertEqual(self.client.post(search_url, query).status_code, 302)
        self.assertEqual(self.client.post(search_url, query).status_code, 429)
        statement_url = reverse('tracker:download_transfer_statement', args=[transfer.pk])
        self.assertEqual(self.client.get(statement_url).status_code, 200)
        self.assertEqual(self.client.get(statement_url).status_code, 429)
        usage = MonthlyUsage.objects.get(identity=f'user:{user.pk}')
        self.assertEqual((usage.searches, usage.downloads), (1, 1))

