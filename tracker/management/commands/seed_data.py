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
        if not WireTransfer.objects.filter(uetr=uetr3).exists():
            t3 = WireTransfer.objects.create(
                uetr=uetr3,
                reference_number="HSBC-FT-20260331-59427",
                date_of_payment=datetime.strptime("2026-03-31", "%Y-%m-%d").date(),
                amount=Decimal('79998940.00'),
                currency="EUR",
                sender_name="EXCLUSIVE MEDIA LIMITED",
                sender_account="02107783",
                sender_bank_name="HSBC UK BANK PLC",
                sender_bank_bic="HBUKGB4156B",
                beneficiary_name="SWIFT ASIA PACIFIC LIMITED",
                beneficiary_account="853065431838",
                beneficiary_bank_name="THE HONGKONG AND SHANGHAI BANKING CORPORATION LIMITED (HSBC)",
                beneficiary_bank_bic="HSBCHKHHHKH",
                charge_type="OUR",
                status="ACCC",
                status_reason="Delivery Status: 100% /// GLOBAL ACK 973 LOCAL SWIFT ACK ->>> DELIVER. MT103 direct cash transfer completed and credited to beneficiary customer account.",
                eta_delivery=timezone.make_aware(datetime.strptime("2026-03-31 14:48:02", "%Y-%m-%d %H:%M:%S"))
            )

            TrackingStep.objects.create(
                transfer=t3,
                step_order=1,
                bank_name="HSBC UK BANK PLC",
                bank_bic="HBUKGB4156B",
                location="331 Lord St, Southport, United Kingdom",
                role="Ordering Institution",
                status_label="Original Sent to SWIFT (ACK)",
                status_code="ACCP",
                timestamp=timezone.make_aware(datetime.strptime("2026-03-31 14:24:17", "%Y-%m-%d %H:%M:%S")),
                fee_deducted=Decimal('0.00'),
                details="MT 103 Direct Cash Transfer initiated. Sender: EXCLUSIVE MEDIA LIMITED (A/C: 02107783). Priority: URGENT."
            )
            TrackingStep.objects.create(
                transfer=t3,
                step_order=2,
                bank_name="Brussels SWIFT Clearing / Bank Sender Network",
                bank_bic="SWHQBEBBFIN",
                location="Brussels, Belgium",
                role="SWIFT Network Intermediary",
                status_label="Global Delivery ACK 973 (ACSP)",
                status_code="ACSP",
                timestamp=timezone.make_aware(datetime.strptime("2026-03-31 14:35:10", "%Y-%m-%d %H:%M:%S")),
                fee_deducted=Decimal('0.00'),
                details="Via Brussels SWIFT / Bank Serial ID: 8D 32 DF 55 DE B9 17.715. Message State: 103 transmitted successfully. Delivery status: 100%."
            )
            TrackingStep.objects.create(
                transfer=t3,
                step_order=3,
                bank_name="The Hongkong and Shanghai Banking Corporation Limited (HSBC)",
                bank_bic="HSBCHKHHHKH",
                location="1 Queen Road, Central, Hong Kong",
                role="Beneficiary Institution",
                status_label="Credited to Account (ACCC)",
                status_code="ACCC",
                timestamp=timezone.make_aware(datetime.strptime("2026-03-31 14:48:02", "%Y-%m-%d %H:%M:%S")),
                fee_deducted=Decimal('0.00'),
                details="Funds received: EUR 79,998,940.00. Credited to SWIFT ASIA PACIFIC LIMITED (A/C: 853065431838). Transfer time: 14:48:02. Approval code: APV-HSBC-310326-F9C8D4E2."
            )

        self.stdout.write(self.style.SUCCESS("Sample wire transfers seeded successfully!"))
