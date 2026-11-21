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
from django.utils.http import url_has_allowed_host_and_scheme
from django.db.models import Q
from django.core.paginator import Paginator

from .forms import (
    UserLoginForm,
    UserRegisterForm,
    UserProfileForm,
    UserPasswordChangeForm,
    AdminUserCreateForm,
    AdminUserEditForm,
    AdminResetPasswordForm,
)
from .quotas import quota_status

User = get_user_model()


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

            if user.is_staff:
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
        if form.is_valid():
            user = form.save()
            auth_login(request, user)
            messages.success(request, f"Welcome to Ohmyfin, {user.first_name or user.username}! Your account is now active.")
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
    })


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
# User Management Views (Staff & Admin Only)
# ---------------------------------------------------------

@staff_member_required
def user_list_view(request):
    """
    Comprehensive User Management Dashboard.
    Displays user list with search, filter, pagination, and status metrics.
    """
    query = request.GET.get('q', '').strip()
    role_filter = request.GET.get('role', 'all')
    status_filter = request.GET.get('status', 'all')

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
        'total_users': total_users,
        'active_users': active_users,
        'staff_users': staff_users,
        'superuser_count': superuser_count,
    })


@staff_member_required
def user_create_view(request):
    """
    Staff/Admin view to create a new user account.
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


@staff_member_required
def user_edit_view(request, user_id):
    """
    Staff/Admin view to edit user account details and permissions.
    """
    target_user = get_object_or_404(User, pk=user_id)

    if request.method == 'POST':
        form = AdminUserEditForm(request.POST, instance=target_user)
        if form.is_valid():
            # Safety check: if target is self and currently superuser, verify not unsetting superuser
            if target_user == request.user and request.user.is_superuser:
                if not form.cleaned_data.get('is_superuser'):
                    messages.error(request, "You cannot remove superuser privileges from your own account.")
                    return redirect('accounts:user_edit', user_id=target_user.pk)
                if not form.cleaned_data.get('is_active'):
                    messages.error(request, "You cannot deactivate your own account.")
                    return redirect('accounts:user_edit', user_id=target_user.pk)

            updated_user = form.save()
            messages.success(request, f"User '{updated_user.username}' updated successfully.")
            return redirect('accounts:user_list')
    else:
        form = AdminUserEditForm(instance=target_user)

    return render(request, 'accounts/user_edit.html', {
        'form': form,
        'target_user': target_user,
    })


@staff_member_required
def user_password_view(request, user_id):
    """
    Staff/Admin view to reset password for a user.
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


@staff_member_required
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


@staff_member_required
def user_delete_view(request, user_id):
    """
    Staff/Admin view to delete a user account with confirmation.
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
