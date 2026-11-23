from datetime import date, timedelta, datetime
from decimal import Decimal
from django.core.management.base import BaseCommand
from django.utils import timezone
from tracker.models import WireTransfer, TrackingStep


class Command(BaseCommand):
    help = "Seed fictional, unpublished payment records for local demonstration"

    def handle(self, *args, **options):
        # 1. USD Transfer - In Transit
        uetr1 = "c2b9a762-b91b-4df2-8e77-508b981f4f5a"
        if not WireTransfer.objects.filter(uetr=uetr1).exists():
            t1 = WireTransfer.objects.create(
                uetr=uetr1,
                reference_number="SWIFT-USD-88910",
                date_of_payment=date.today() - timedelta(days=1),
                amount=Decimal('125000.00'),
                currency="USD",
                sender_name="ALPHA GLOBAL TRADING LLC",
                sender_account="US89SVBL9876543210",
                sender_bank_name="Silicon Valley Bank (First Citizens)",
                sender_bank_bic="SVBLUS6S",
                beneficiary_name="PRIME HORIZON GENERAL TRADING FZ-LLC",
                beneficiary_account="AE070331234567890123456",
                beneficiary_bank_name="Emirates NBD Bank PJSC",
                beneficiary_bank_bic="EBILAEAD",
                charge_type="SHA",
                status="ACSP",
                status_reason="Settlement progressing. Funds routed through US correspondent and cleared for credit at beneficiary institution.",
                eta_delivery=timezone.now() + timedelta(hours=6)
            )

            now = timezone.now()
            TrackingStep.objects.create(
                transfer=t1,
                step_order=1,
                bank_name="Silicon Valley Bank",
                bank_bic="SVBLUS6S",
                location="San Francisco, US",
                role="Ordering Institution",
                status_label="Payment Initiated (ACCP)",
                status_code="ACCP",
                timestamp=now - timedelta(hours=14),
                fee_deducted=Decimal('25.00'),
                details="Customer debited. pacs.008 instruction released to SWIFT FIN network with UETR."
            )
            TrackingStep.objects.create(
                transfer=t1,
                step_order=2,
                bank_name="JPMorgan Chase Bank, N.A.",
                bank_bic="CHASUS33",
                location="New York, US",
                role="Intermediary Institution",
                status_label="Settled & Transferred (ACSP)",
                status_code="ACSP",
                timestamp=now - timedelta(hours=9),
                fee_deducted=Decimal('15.00'),
                details="Nostro account debited. Routing validated against Standard Settlement Instructions (SSI)."
            )
            TrackingStep.objects.create(
                transfer=t1,
                step_order=3,
                bank_name="Emirates NBD Bank PJSC",
                bank_bic="EBILAEAD",
                location="Dubai, AE",
                role="Beneficiary Institution",
                status_label="Processing / Awaiting Posting (ACSP)",
                status_code="ACSP",
                timestamp=now - timedelta(hours=2),
                fee_deducted=Decimal('0.00'),
                details="Inward payment message matched. UAE Central Bank Purpose Code verified (GDE - Goods Exported). Posting in progress."
            )

        # 2. EUR Transfer - Credited / Completed
        uetr2 = "7f81a2b3-56c4-4e9a-9d21-44bb88cc1100"
        if not WireTransfer.objects.filter(uetr=uetr2).exists():
            t2 = WireTransfer.objects.create(
                uetr=uetr2,
                reference_number="EUR-WIRE-55421",
                date_of_payment=date.today() - timedelta(days=2),
                amount=Decimal('75000.00'),
                currency="EUR",
                sender_name="NOVATRONIC SOLUTIONS GMBH",
                sender_account="DE89370400440532013000",
                sender_bank_name="Deutsche Bank AG",
                sender_bank_bic="DEUTDEDD",
                beneficiary_name="OAKRIDGE CAPITAL PARTNERS LTD",
                beneficiary_account="GB29NWBK60161331926819",
                beneficiary_bank_name="Barclays Bank UK PLC",
                beneficiary_bank_bic="BARCGB22",
                charge_type="OUR",
                status="ACCC",
                status_reason="Payment completed. Credited in full to beneficiary customer account with zero intermediary deductions.",
                eta_delivery=timezone.now() - timedelta(hours=5)
            )

            now = timezone.now()
            TrackingStep.objects.create(
                transfer=t2,
                step_order=1,
                bank_name="Deutsche Bank AG",
                bank_bic="DEUTDEDD",
                location="Frankfurt, DE",
                role="Ordering Institution",
                status_label="Dispatched (ACCP)",
                status_code="ACCP",
                timestamp=now - timedelta(days=2),
                fee_deducted=Decimal('10.00'),
                details="SEPA / SWIFT MT103 dispatched."
            )
            TrackingStep.objects.create(
                transfer=t2,
                step_order=2,
                bank_name="Barclays Bank UK PLC",
                bank_bic="BARCGB22",
                location="London, GB",
                role="Beneficiary Institution",
                status_label="Settled & Credited (ACCC)",
                status_code="ACCC",
                timestamp=now - timedelta(days=1, hours=8),
                fee_deducted=Decimal('0.00'),
                details="Payment posted directly to beneficiary GBP/EUR multi-currency account."
            )

        # 3. HSBC Large Value Wire (€79,998,940.00)
        uetr3 = "b4e791d2-a6f5-48c3-89d1-5c82e7a9b3f0"
        t3 = WireTransfer.objects.filter(uetr=uetr3).first()
        if not t3:
            t3 = WireTransfer.objects.create(
                uetr=uetr3,
                reference_number="HSBC-FT-20260331-59427",
                date_of_payment=datetime.strptime("2026-03-31", "%Y-%m-%d").date(),
                amount=Decimal('79998940.00'),
                currency="EUR",
                sender_name="EXCLUSIVE MEDIA LIMITED",
                sender_account="GB04 HBUK 4042 3002 1077 83",
                sender_bank_name="HSBC UK BANK PLC",
                sender_bank_bic="HBUKGB4156B",
                beneficiary_name="SWIFT ASIA PACIFIC LIMITED",
                beneficiary_account="853 065431 838",
                beneficiary_bank_name="THE HONGKONG AND SHANGHAI BANKING CORPORATION LIMITED (HSBC)",
                beneficiary_bank_bic="HSBCHKHHHKH",
                charge_type="SHA",
                status="HOLD",
                status_reason='Funds are secured at the destination bank but have been flagged by the automated AML system due to the exceptionally high transaction volume (€ 79.9M). Credit to account (853 065431 838) is suspended pending mandatory "Source of Funds" documentation.',
                source_type="PACS008",
                source_description="HSBC Irrevocable Payment Advice / SWIFT Confirmation (ISO 20022 pacs.008) & SWIFT MT103 GPI Audit (MUR: HSBC-FT-20260331-59427)",
                status_observed_at=timezone.make_aware(datetime.strptime("2026-03-31 16:10:05", "%Y-%m-%d %H:%M:%S")),
                eta_delivery=timezone.make_aware(datetime.strptime("2026-03-31 14:48:02", "%Y-%m-%d %H:%M:%S")),
                is_published=True
            )

            TrackingStep.objects.create(
                transfer=t3,
                step_order=1,
                bank_name="HSBC UK BANK PLC",
                bank_bic="HBUKGB4156B",
                location="331 Lord St, Southport / 8 Canada Square, London, UK",
                role="Ordering Institution",
                status_label="Initiation by Ordering Bank (Debit Confirmed)",
                status_code="ACSP",
                timestamp=timezone.make_aware(datetime.strptime("2026-03-31 14:20:12", "%Y-%m-%d %H:%M:%S")),
                fee_deducted=Decimal('0.00'),
                details="Funds debited from EXCLUSIVE MEDIA LIMITED (A/C: GB04 HBUK 4042 3002 1077 83 / 02107783). HSBC compliance checks passed."
            )
            TrackingStep.objects.create(
                transfer=t3,
                step_order=2,
                bank_name="SWIFT Secure IP Network (SIPN)",
                bank_bic="HBUKGB4156B",
                location="Network Node: HBUKGB41_LIVE (Brussels)",
                role="SWIFT Network Processing",
                status_label="SWIFT Network Processing (Network ACK)",
                status_code="ACSP",
                timestamp=timezone.make_aware(datetime.strptime("2026-03-31 14:24:17", "%Y-%m-%d %H:%M:%S")),
                fee_deducted=Decimal('0.00'),
                details="FIN 103 GPI message generated and routed. MESSAGE HAS BEEN TRANSMITTED SUCCESSFULLY. ISO 20022 / CBPR+ (pacs.008.001.08) delivery status: DELIVERED / SAFE STORE ACK. Network Reference: 31032026HSBCGB4100847291."
            )
            TrackingStep.objects.create(
                transfer=t3,
                step_order=3,
                bank_name="Central Bank Clearing Node",
                bank_bic="HBUKGB4156B",
                location="Central Clearing Audit System",
                role="Clearing Node",
                status_label="Central Bank Clearing Node (ACSP)",
                status_code="ACSP",
                timestamp=timezone.make_aware(datetime.strptime("2026-03-31 15:20:25", "%Y-%m-%d %H:%M:%S")),
                fee_deducted=Decimal('0.00'),
                details="Central Bank Handshake Confirmed. Pending Regulatory & Compliance Review passed successfully. Packet delivered to international gateway."
            )
            TrackingStep.objects.create(
                transfer=t3,
                step_order=4,
                bank_name="THE HONGKONG AND SHANGHAI BANKING CORPORATION LIMITED (HSBC)",
                bank_bic="HSBCHKHHHKH",
                location="1 Queen's Road Central, Hong Kong",
                role="Destination Gateway",
                status_label="Arrival at Destination Gateway (RCVD at Beneficiary Bank)",
                status_code="ACSP",
                timestamp=timezone.make_aware(datetime.strptime("2026-03-31 16:10:05", "%Y-%m-%d %H:%M:%S")),
                fee_deducted=Decimal('0.00'),
                details="Message successfully received by THE HONGKONG AND SHANGHAI BANKING CORPORATION LIMITED (HSBC) processing center (Hong Kong)."
            )
            TrackingStep.objects.create(
                transfer=t3,
                step_order=5,
                bank_name="THE HONGKONG AND SHANGHAI BANKING CORPORATION LIMITED (HSBC)",
                bank_bic="HSBCHKHHHKH",
                location="1 Queen's Road Central, Hong Kong",
                role="Beneficiary Institution",
                status_label="Final Credit to Beneficiary Account (Status: SUSPENDED)",
                status_code="HOLD",
                timestamp=timezone.make_aware(datetime.strptime("2026-03-31 16:10:05", "%Y-%m-%d %H:%M:%S")),
                fee_deducted=Decimal('0.00'),
                details='Funds are secured at the destination bank but have been flagged by the automated AML system due to the exceptionally high transaction volume (€ 79.9M). Credit to account (853 065431 838) is suspended pending mandatory "Source of Funds" documentation.'
            )

        self.stdout.write(self.style.SUCCESS("Sample wire transfers seeded successfully!"))
