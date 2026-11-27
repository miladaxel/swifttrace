from functools import wraps
from io import BytesIO
import mimetypes

from django.conf import settings
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth import (
    login as auth_login,
    logout as auth_logout,
    update_session_auth_hash,
    get_user_model,
)
from django.contrib.auth.decorators import login_required
from django.contrib.admin.views.decorators import staff_member_required
from django.core.exceptions import PermissionDenied
from django.http import FileResponse, Http404, HttpResponse
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.contrib.auth.views import redirect_to_login
from django.views.decorators.http import require_POST
from django.views.decorators.cache import never_cache
from django.db.models import Q
from django.db import transaction
from django.core.paginator import Paginator

from .forms import (
    UserLoginForm,
    UserRegisterForm,
    UserProfileForm,
    UserPasswordChangeForm,
    AdminUserCreateForm,
    AdminUserEditForm,
    AdminResetPasswordForm,
    PaymentProofForm,
    ReviewDecisionForm,
)
from .models import MembershipTier, PlanPurchase
from .purchase_review import review_purchase
from .rate_limit import record_login_attempt, record_registration_attempt, reserve_registration_success
from .quotas import expire_memberships, limits_for, membership_for, quota_status, tier_for

User = get_user_model()


def superuser_required(view_func):
    """Reserve account administration for active staff superusers."""
    @staff_member_required
    @wraps(view_func)
    def wrapped(request, *args, **kwargs):
        if not request.user.is_superuser:
            raise PermissionDenied
        return view_func(request, *args, **kwargs)

    return wrapped


# ---------------------------------------------------------
# Authentication Views (Login, Logout, Register)
# ---------------------------------------------------------

def login_view(request):
    """
    User login view supporting username or email.
    """
    if request.user.is_authenticated:
        return redirect('pages:home')

    next_url = request.GET.get('next') or request.POST.get('next') or ''

    if request.method == 'POST':
        form = UserLoginForm(request.POST)
        allowed, retry_after = record_login_attempt(request)
        if not allowed:
            form.add_error(None, 'Too many sign-in attempts. Please try again later.')
            response = render(request, 'accounts/login.html', {'form': form, 'next': next_url}, status=429)
            response['Retry-After'] = str(retry_after)
            response['Cache-Control'] = 'private, no-store'
            return response
        if form.is_valid():
            user = form.get_user()
            auth_login(request, user)

            remember_me = form.cleaned_data.get('remember_me')
            if not remember_me:
                # Browser-session only
                request.session.set_expiry(0)
            else:
                # 2 weeks
                request.session.set_expiry(1209600)

            user_display = user.get_full_name() or user.username
            messages.success(request, f"Welcome back, {user_display}!")

            if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
                return redirect(next_url)

            if user.is_staff and user.has_perm('tracker.view_wiretransfer'):
                return redirect('dashboard:index')
            return redirect('pages:home')
    else:
        form = UserLoginForm()

    return render(request, 'accounts/login.html', {
        'form': form,
        'next': next_url,
    })


def logout_view(request):
    """
    User logout view (supports both POST and GET).
    """
    if request.user.is_authenticated:
        auth_logout(request)
        messages.info(request, "You have been signed out successfully.")
    return redirect('pages:home')


def register_view(request):
    """
    Public user registration view.
    """
    if request.user.is_authenticated:
        return redirect('pages:home')

    next_url = request.GET.get('next') or request.POST.get('next') or ''

    if request.method == 'POST':
        form = UserRegisterForm(request.POST)
        allowed, retry_after = record_registration_attempt(request)
        if not allowed:
            response = render(request, 'accounts/register.html', {
                'form': UserRegisterForm(), 'next': next_url,
                'rate_limit_message': 'Too many registration attempts. Please try again later.',
            }, status=429)
            response['Retry-After'] = str(retry_after)
            response['Cache-Control'] = 'private, no-store'
            return response
        if form.is_valid():
            with transaction.atomic():
                allowed, retry_after = reserve_registration_success(request)
                if allowed:
                    user = form.save()
            if not allowed:
                response = render(request, 'accounts/register.html', {
                    'form': UserRegisterForm(), 'next': next_url,
                    'rate_limit_message': 'Too many accounts have been created from this connection. Please try again later.',
                }, status=429)
                response['Retry-After'] = str(retry_after)
                response['Cache-Control'] = 'private, no-store'
                return response
            auth_login(request, user)
            messages.success(request, f"Welcome to Swifttrace, {user.first_name or user.username}! Your account is now active.")
            if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
                return redirect(next_url)
            return redirect('pages:home')
    else:
        form = UserRegisterForm()

    return render(request, 'accounts/register.html', {
        'form': form,
        'next': next_url,
    })


@login_required
def profile_view(request):
    """
    Logged-in user profile view to view stats and update details.
    """
    if request.method == 'POST':
        form = UserProfileForm(request.POST, instance=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, "Your profile details have been updated successfully.")
            return redirect('accounts:profile')
    else:
        form = UserProfileForm(instance=request.user)

    tier, usage = quota_status(request)
    return render(request, 'accounts/profile.html', {
        'form': form,
        'membership_tier': tier,
        'monthly_usage': usage,
        'membership_limits': limits_for(request),
        'membership_expires_at': membership_for(request.user).expires_at,
        'recent_purchases': PlanPurchase.objects.filter(user=request.user).select_related('tier')[:3],
    })


@require_POST
def start_plan_purchase_view(request, level):
    if not request.user.is_authenticated:
        return redirect_to_login(reverse('pages:pricing'), login_url=settings.LOGIN_URL)
    if level not in (MembershipTier.SILVER, MembershipTier.GOLD):
        raise Http404('This plan is not available for purchase.')
    tier = get_object_or_404(MembershipTier, pk=level)
    submitted = PlanPurchase.objects.filter(
        user=request.user, tier=tier, status=PlanPurchase.SUBMITTED,
    ).first()
    if submitted:
        messages.info(request, 'Your payment proof for this plan is already awaiting review.')
        return redirect('accounts:plan_purchase', purchase_id=submitted.pk)
    if not (tier.monthly_price_usdt and tier.payment_url and tier.payment_network):
        messages.warning(request, 'Payment instructions for this plan are not available yet.')
        return redirect('pages:pricing')
    tier_for(request)
    purchase, _ = PlanPurchase.objects.get_or_create(
        user=request.user, tier=tier, status=PlanPurchase.AWAITING_PAYMENT,
        defaults={
            'price_usdt': tier.monthly_price_usdt,
            'monthly_search_limit': tier.monthly_search_limit,
            'monthly_download_limit': tier.monthly_download_limit,
            'payment_url': tier.payment_url,
            'payment_network': tier.payment_network,
        },
    )
    return redirect('accounts:plan_purchase', purchase_id=purchase.pk)


@login_required
@never_cache
def plan_purchase_view(request, purchase_id):
    purchase = get_object_or_404(PlanPurchase.objects.select_related('tier'), pk=purchase_id, user=request.user)
    if request.method == 'POST' and purchase.status == PlanPurchase.AWAITING_PAYMENT:
        form = PaymentProofForm(request.POST, request.FILES, instance=purchase)
        if form.is_valid():
            proof = form.save(commit=False)
            proof.status = PlanPurchase.SUBMITTED
            proof.submitted_at = timezone.now()
            proof.save(update_fields=['txid', 'receipt_image', 'status', 'submitted_at'])
            messages.success(request, 'Payment proof submitted. An administrator can now review it.')
            return redirect('accounts:plan_purchase', purchase_id=purchase.pk)
    elif request.method == 'POST':
        messages.info(request, 'This payment proof has already been submitted.')
        return redirect('accounts:plan_purchase', purchase_id=purchase.pk)
    else:
        form = PaymentProofForm(instance=purchase) if purchase.status == PlanPurchase.AWAITING_PAYMENT else None
    return render(request, 'accounts/plan_purchase.html', {'purchase': purchase, 'form': form})


@login_required
def plan_purchase_history_view(request):
    purchases = PlanPurchase.objects.filter(user=request.user).select_related('tier')
    return render(request, 'accounts/plan_purchase_history.html', {'purchases': purchases})


@login_required
@never_cache
def purchase_qr_view(request, purchase_id):
    purchase = get_object_or_404(
        PlanPurchase, pk=purchase_id, user=request.user, status=PlanPurchase.AWAITING_PAYMENT,
    )
    import qrcode

    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=8, border=4)
    qr.add_data(purchase.payment_url)
    qr.make(fit=True)
    output = BytesIO()
    qr.make_image(fill_color='#172033', back_color='white').save(output, format='PNG')
    response = HttpResponse(output.getvalue(), content_type='image/png')
    response['Cache-Control'] = 'private, no-store'
    response['X-Content-Type-Options'] = 'nosniff'
    return response


@login_required
@never_cache
def purchase_receipt_view(request, purchase_id):
    purchase = get_object_or_404(PlanPurchase, pk=purchase_id)
    if purchase.user_id != request.user.pk and not request.user.is_superuser:
        raise Http404('Receipt not found.')
    if not purchase.receipt_image:
        raise Http404('Receipt not found.')
    try:
        purchase.receipt_image.open('rb')
    except (OSError, ValueError):
        raise Http404('Receipt image is unavailable.')
    content_type = mimetypes.guess_type(purchase.receipt_image.name)[0] or 'application/octet-stream'
    response = FileResponse(purchase.receipt_image, content_type=content_type)
    response['Cache-Control'] = 'private, no-store'
    response['X-Content-Type-Options'] = 'nosniff'
    return response


@superuser_required
@never_cache
def purchase_review_list_view(request):
    status_filter = request.GET.get('status', PlanPurchase.SUBMITTED)
    valid_statuses = {value for value, _ in PlanPurchase.STATUS_CHOICES} | {'all'}
    if status_filter not in valid_statuses:
        status_filter = PlanPurchase.SUBMITTED
    tier_filter = request.GET.get('tier', 'all')
    if tier_filter not in (MembershipTier.SILVER, MembershipTier.GOLD, 'all'):
        tier_filter = 'all'
    query = request.GET.get('q', '').strip()

    purchases = PlanPurchase.objects.select_related('user', 'tier', 'reviewed_by')
    if status_filter != 'all':
        purchases = purchases.filter(status=status_filter)
    if tier_filter != 'all':
        purchases = purchases.filter(tier_id=tier_filter)
    if query:
        purchases = purchases.filter(
            Q(user__username__icontains=query) | Q(user__email__icontains=query) | Q(txid__icontains=query)
        )

    page_obj = Paginator(purchases, 15).get_page(request.GET.get('page'))
    query_params = request.GET.copy()
    query_params.pop('page', None)
    return render(request, 'accounts/purchase_review_list.html', {
        'page_obj': page_obj,
        'purchases': page_obj.object_list,
        'status_filter': status_filter,
        'tier_filter': tier_filter,
        'query': query,
        'filter_query': query_params.urlencode(),
        'pending_count': PlanPurchase.objects.filter(status=PlanPurchase.SUBMITTED).count(),
        'approved_count': PlanPurchase.objects.filter(status=PlanPurchase.APPROVED).count(),
        'rejected_count': PlanPurchase.objects.filter(status=PlanPurchase.REJECTED).count(),
        'total_count': PlanPurchase.objects.count(),
        'status_choices': [('submitted', 'Needs review'), ('awaiting_payment', 'Awaiting payment'), ('approved', 'Approved'), ('rejected', 'Rejected'), ('all', 'All')],
    })


def render_purchase_review(request, purchase, form=None, status=200):
    return render(request, 'accounts/purchase_review_detail.html', {
        'purchase': purchase,
        'membership': membership_for(purchase.user),
        'form': form or ReviewDecisionForm(),
    }, status=status)


@superuser_required
@never_cache
def purchase_review_detail_view(request, purchase_id):
    purchase = get_object_or_404(
        PlanPurchase.objects.select_related('user', 'tier', 'reviewed_by'), pk=purchase_id,
    )
    return render_purchase_review(request, purchase)


@superuser_required
@require_POST
def purchase_review_action_view(request, purchase_id):
    purchase = get_object_or_404(
        PlanPurchase.objects.select_related('user', 'tier', 'reviewed_by'), pk=purchase_id,
    )
    form = ReviewDecisionForm(request.POST)
    if not form.is_valid():
        return render_purchase_review(request, purchase, form, status=400)
    purchase, changed = review_purchase(
        purchase.pk, request.user, form.cleaned_data['decision'], form.cleaned_data['note'],
    )
    if not changed:
        messages.warning(request, 'This request has already been reviewed or is not ready for review.')
    elif purchase.status == PlanPurchase.APPROVED:
        messages.success(request, f'{purchase.user.username} now has {purchase.tier} access until {purchase.access_expires_at:%Y-%m-%d}.')
    else:
        messages.success(request, f'{purchase.user.username}\'s payment request was rejected.')
    return redirect('accounts:purchase_review_detail', purchase_id=purchase.pk)


@login_required
def change_password_view(request):
    """
    Logged-in user can change their password securely.
    """
    if request.method == 'POST':
        form = UserPasswordChangeForm(user=request.user, data=request.POST)
        if form.is_valid():
            new_password = form.cleaned_data['new_password']
            request.user.set_password(new_password)
            request.user.save()
            update_session_auth_hash(request, request.user)
            messages.success(request, "Your password has been changed successfully.")
            return redirect('accounts:profile')
    else:
        form = UserPasswordChangeForm(user=request.user)

    return render(request, 'accounts/change_password.html', {
        'form': form,
    })


# ---------------------------------------------------------
# User Management Views (Superusers Only)
# ---------------------------------------------------------

@superuser_required
def user_list_view(request):
    """
    Comprehensive User Management Dashboard.
    Displays user list with search, filter, pagination, and status metrics.
    """
    query = request.GET.get('q', '').strip()
    role_filter = request.GET.get('role', 'all')
    status_filter = request.GET.get('status', 'all')
    tier_filter = request.GET.get('tier', 'all')

    expire_memberships()
    users_qs = User.objects.select_related('membership__tier').order_by('-date_joined')

    # Apply search filter
    if query:
        users_qs = users_qs.filter(
            Q(username__icontains=query) |
            Q(email__icontains=query) |
            Q(first_name__icontains=query) |
            Q(last_name__icontains=query)
        )

    # Apply role filter
    if role_filter == 'superuser':
        users_qs = users_qs.filter(is_superuser=True)
    elif role_filter == 'staff':
        users_qs = users_qs.filter(is_staff=True, is_superuser=False)
    elif role_filter == 'regular':
        users_qs = users_qs.filter(is_staff=False, is_superuser=False)

    # Apply status filter
    if status_filter == 'active':
        users_qs = users_qs.filter(is_active=True)
    elif status_filter == 'inactive':
        users_qs = users_qs.filter(is_active=False)

    if tier_filter in (MembershipTier.FREE, MembershipTier.SILVER, MembershipTier.GOLD):
        users_qs = users_qs.filter(membership__tier_id=tier_filter)
    else:
        tier_filter = 'all'

    # Key Statistics
    total_users = User.objects.count()
    active_users = User.objects.filter(is_active=True).count()
    staff_users = User.objects.filter(is_staff=True).count()
    superuser_count = User.objects.filter(is_superuser=True).count()

    # Pagination
    paginator = Paginator(users_qs, 15)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    return render(request, 'accounts/user_list.html', {
        'page_obj': page_obj,
        'users': page_obj.object_list,
        'query': query,
        'role_filter': role_filter,
        'status_filter': status_filter,
        'tier_filter': tier_filter,
        'total_users': total_users,
        'active_users': active_users,
        'staff_users': staff_users,
        'superuser_count': superuser_count,
        'pending_count': PlanPurchase.objects.filter(status=PlanPurchase.SUBMITTED).count(),
        'pending_purchases': PlanPurchase.objects.filter(status=PlanPurchase.SUBMITTED).select_related('user', 'tier').order_by('submitted_at')[:3],
    })


@superuser_required
def user_create_view(request):
    """
    Superuser view to create a new user account.
    """
    if request.method == 'POST':
        form = AdminUserCreateForm(request.POST)
        if form.is_valid():
            new_user = form.save()
            messages.success(request, f"User '{new_user.username}' created successfully.")
            return redirect('accounts:user_list')
    else:
        form = AdminUserCreateForm()

    return render(request, 'accounts/user_create.html', {
        'form': form,
    })


@superuser_required
def user_edit_view(request, user_id):
    """
    Superuser view to edit user account details and permissions.
    """
    target_user = get_object_or_404(User, pk=user_id)

    if request.method == 'POST':
        form = AdminUserEditForm(request.POST, instance=target_user)
        if form.is_valid():
            # Prevent an administrator from locking themselves out.
            if target_user == request.user and request.user.is_superuser:
                if not form.cleaned_data.get('is_superuser'):
                    messages.error(request, "You cannot remove superuser privileges from your own account.")
                    return redirect('accounts:user_edit', user_id=target_user.pk)
                if not form.cleaned_data.get('is_active'):
                    messages.error(request, "You cannot deactivate your own account.")
                    return redirect('accounts:user_edit', user_id=target_user.pk)
                if not form.cleaned_data.get('is_staff'):
                    messages.error(request, "You cannot remove staff access from your own account.")
                    return redirect('accounts:user_edit', user_id=target_user.pk)

            updated_user = form.save()
            messages.success(request, f"User '{updated_user.username}' updated successfully.")
            return redirect('accounts:user_list')
    else:
        form = AdminUserEditForm(instance=target_user)

    return render(request, 'accounts/user_edit.html', {
        'form': form,
        'target_user': target_user,
        'target_membership': membership_for(target_user),
        'user_purchases': PlanPurchase.objects.filter(user=target_user).select_related('tier')[:5],
    })


@superuser_required
def user_password_view(request, user_id):
    """
    Superuser view to reset password for a user.
    """
    target_user = get_object_or_404(User, pk=user_id)

    if request.method == 'POST':
        form = AdminResetPasswordForm(target_user=target_user, data=request.POST)
        if form.is_valid():
            new_password = form.cleaned_data['new_password']
            target_user.set_password(new_password)
            target_user.save()

            if target_user == request.user:
                update_session_auth_hash(request, target_user)

            messages.success(request, f"Password for user '{target_user.username}' has been updated.")
            return redirect('accounts:user_list')
    else:
        form = AdminResetPasswordForm(target_user=target_user)

    return render(request, 'accounts/user_password.html', {
        'form': form,
        'target_user': target_user,
    })


@superuser_required
@require_POST
def user_toggle_status_view(request, user_id):
    """
    Quickly toggle a user's active/inactive status.
    """
    target_user = get_object_or_404(User, pk=user_id)

    if target_user == request.user:
        messages.error(request, "You cannot deactivate your own account.")
        return redirect('accounts:user_list')

    target_user.is_active = not target_user.is_active
    target_user.save()

    status_str = "activated" if target_user.is_active else "deactivated"
    messages.success(request, f"User '{target_user.username}' has been {status_str}.")
    return redirect('accounts:user_list')


@superuser_required
def user_delete_view(request, user_id):
    """
    Superuser view to delete a user account with confirmation.
    """
    target_user = get_object_or_404(User, pk=user_id)

    if target_user == request.user:
        messages.error(request, "You cannot delete your own account.")
        return redirect('accounts:user_list')

    if request.method == 'POST':
        username = target_user.username
        target_user.delete()
        messages.success(request, f"User '{username}' has been permanently deleted.")
        return redirect('accounts:user_list')

    return render(request, 'accounts/user_delete_confirm.html', {
        'target_user': target_user,
    })
