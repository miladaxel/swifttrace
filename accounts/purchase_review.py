from calendar import monthrange
from django.db import transaction
from django.utils import timezone

from .models import PlanPurchase, UserMembership


def one_month_later(moment):
    year = moment.year + (moment.month == 12)
    month = 1 if moment.month == 12 else moment.month + 1
    day = min(moment.day, monthrange(year, month)[1])
    return moment.replace(year=year, month=month, day=day)


def review_purchase(purchase_id, reviewer, decision, note=''):
    """Apply one review decision and its membership change in one transaction."""
    if decision not in (PlanPurchase.APPROVED, PlanPurchase.REJECTED):
        raise ValueError('Invalid review decision')
    if decision == PlanPurchase.REJECTED and not note.strip():
        raise ValueError('A rejection reason is required')

    with transaction.atomic():
        purchase = PlanPurchase.objects.select_for_update().select_related('tier', 'user').get(pk=purchase_id)
        if purchase.status != PlanPurchase.SUBMITTED or not purchase.txid or not purchase.receipt_image:
            return purchase, False

        now = timezone.now()
        if decision == PlanPurchase.APPROVED:
            membership, _ = UserMembership.objects.select_for_update().get_or_create(user=purchase.user)
            base = now
            keeping_active_limits = membership.tier_id == purchase.tier_id and membership.expires_at and membership.expires_at > now
            if keeping_active_limits:
                base = membership.expires_at
            else:
                membership.monthly_search_limit = (
                    purchase.monthly_search_limit if purchase.monthly_search_limit is not None
                    else purchase.tier.monthly_search_limit
                )
                membership.monthly_download_limit = (
                    purchase.monthly_download_limit if purchase.monthly_download_limit is not None
                    else purchase.tier.monthly_download_limit
                )
            membership.tier = purchase.tier
            membership.expires_at = one_month_later(base)
            membership.save(update_fields=['tier', 'expires_at', 'monthly_search_limit', 'monthly_download_limit'])
            purchase.access_expires_at = membership.expires_at

        purchase.status = decision
        purchase.reviewed_at = now
        purchase.reviewed_by = reviewer
        purchase.review_note = note.strip()
        purchase.save(update_fields=['status', 'reviewed_at', 'reviewed_by', 'review_note', 'access_expires_at'])
        return purchase, True
