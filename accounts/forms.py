from django import forms
from django.contrib.auth import get_user_model, authenticate
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from .models import MembershipTier, PlanPurchase, UserMembership
from .quotas import membership_for

User = get_user_model()


class PaymentProofForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['txid'].required = True
        self.fields['receipt_image'].required = True

    class Meta:
        model = PlanPurchase
        fields = ('txid', 'receipt_image')
        widgets = {
            'txid': forms.TextInput(attrs={
                'placeholder': 'Paste the transaction ID from your wallet',
                'autocomplete': 'off',
                'class': 'w-full rounded-xl border border-slate-300 px-4 py-3 font-mono text-sm focus:outline-none focus:ring-2 focus:ring-orange-500',
            }),
            'receipt_image': forms.ClearableFileInput(attrs={
                'accept': 'image/jpeg,image/png,image/webp',
                'class': 'block w-full text-sm text-slate-600 file:mr-4 file:rounded-lg file:border-0 file:bg-orange-100 file:px-4 file:py-2 file:font-semibold file:text-orange-700',
            }),
        }

    def clean_txid(self):
        txid = (self.cleaned_data.get('txid') or '').strip().lower()
        if not txid or any(character.isspace() for character in txid):
            raise ValidationError('Enter a transaction ID without spaces.')
        if PlanPurchase.objects.filter(txid=txid).exclude(pk=self.instance.pk).exists():
            raise ValidationError('This transaction ID has already been submitted.')
        return txid


class ReviewDecisionForm(forms.Form):
    decision = forms.ChoiceField(choices=[('approved', 'Approve'), ('rejected', 'Reject')])
    note = forms.CharField(
        required=False, max_length=2000,
        widget=forms.Textarea(attrs={
            'rows': 4,
            'placeholder': 'Required when rejecting. Explain what the customer should correct.',
            'class': 'w-full rounded-xl border border-slate-300 px-4 py-3 text-sm focus:outline-none focus:ring-2 focus:ring-orange-500',
        }),
    )

    def clean(self):
        cleaned_data = super().clean()
        note = (cleaned_data.get('note') or '').strip()
        if cleaned_data.get('decision') == 'rejected' and not note:
            self.add_error('note', 'Enter a reason before rejecting this request.')
        cleaned_data['note'] = note
        return cleaned_data


class UserLoginForm(forms.Form):
    username_or_email = forms.CharField(
        label="Username or Email",
        widget=forms.TextInput(attrs={
            'placeholder': 'Enter your username or email',
            'class': 'w-full px-4 py-2.5 rounded-xl border border-slate-200 text-sm focus:outline-none focus:ring-2 focus:ring-orange-500 focus:border-transparent text-slate-900 bg-white placeholder-slate-400',
            'autocomplete': 'username',
        })
    )
    password = forms.CharField(
        label="Password",
        widget=forms.PasswordInput(attrs={
            'placeholder': '••••••••',
            'class': 'w-full px-4 py-2.5 rounded-xl border border-slate-200 text-sm focus:outline-none focus:ring-2 focus:ring-orange-500 focus:border-transparent text-slate-900 bg-white placeholder-slate-400',
            'autocomplete': 'current-password',
        })
    )
    remember_me = forms.BooleanField(
        required=False,
        initial=True,
        label="Remember me",
        widget=forms.CheckboxInput(attrs={
            'class': 'h-4 w-4 rounded border-slate-300 text-orange-600 focus:ring-orange-500',
        })
    )

    def clean(self):
        cleaned_data = super().clean()
        username_or_email = cleaned_data.get('username_or_email')
        password = cleaned_data.get('password')

        if username_or_email and password:
            # Check if input is email or username
            user = None
            if '@' in username_or_email:
                try:
                    user_obj = User.objects.get(email__iexact=username_or_email)
                    user = authenticate(username=user_obj.username, password=password)
                except User.DoesNotExist:
                    user = None
                except User.MultipleObjectsReturned:
                    # If multiple users have the same email, try first matching active
                    users = User.objects.filter(email__iexact=username_or_email)
                    for u in users:
                        authenticated = authenticate(username=u.username, password=password)
                        if authenticated:
                            user = authenticated
                            break

            if user is None:
                # Try direct username authentication
                user = authenticate(username=username_or_email, password=password)

            if user is None:
                # Check if user exists and password is valid, but user is inactive
                candidates = []
                if '@' in username_or_email:
                    candidates = list(User.objects.filter(email__iexact=username_or_email))
                if not candidates:
                    candidates = list(User.objects.filter(username__iexact=username_or_email))

                for candidate in candidates:
                    if candidate.check_password(password) and not candidate.is_active:
                        raise ValidationError("This user account is inactive. Please contact an administrator.")

                raise ValidationError("Invalid username/email or password.")

            self.user_cache = user

        return cleaned_data

    def get_user(self):
        return getattr(self, 'user_cache', None)


class UserRegisterForm(forms.ModelForm):
    password = forms.CharField(
        label="Password",
        widget=forms.PasswordInput(attrs={
            'placeholder': 'At least 8 characters',
            'class': 'w-full px-4 py-2.5 rounded-xl border border-slate-200 text-sm focus:outline-none focus:ring-2 focus:ring-orange-500 focus:border-transparent text-slate-900 bg-white placeholder-slate-400',
            'autocomplete': 'new-password',
        })
    )
    confirm_password = forms.CharField(
        label="Confirm Password",
        widget=forms.PasswordInput(attrs={
            'placeholder': 'Re-enter your password',
            'class': 'w-full px-4 py-2.5 rounded-xl border border-slate-200 text-sm focus:outline-none focus:ring-2 focus:ring-orange-500 focus:border-transparent text-slate-900 bg-white placeholder-slate-400',
            'autocomplete': 'new-password',
        })
    )

    class Meta:
        model = User
        fields = ['username', 'email', 'first_name', 'last_name']
        widgets = {
            'username': forms.TextInput(attrs={
                'placeholder': 'Choose a unique username',
                'class': 'w-full px-4 py-2.5 rounded-xl border border-slate-200 text-sm focus:outline-none focus:ring-2 focus:ring-orange-500 focus:border-transparent text-slate-900 bg-white placeholder-slate-400',
            }),
            'email': forms.EmailInput(attrs={
                'placeholder': 'name@example.com',
                'class': 'w-full px-4 py-2.5 rounded-xl border border-slate-200 text-sm focus:outline-none focus:ring-2 focus:ring-orange-500 focus:border-transparent text-slate-900 bg-white placeholder-slate-400',
            }),
            'first_name': forms.TextInput(attrs={
                'placeholder': 'First name (optional)',
                'class': 'w-full px-4 py-2.5 rounded-xl border border-slate-200 text-sm focus:outline-none focus:ring-2 focus:ring-orange-500 focus:border-transparent text-slate-900 bg-white placeholder-slate-400',
            }),
            'last_name': forms.TextInput(attrs={
                'placeholder': 'Last name (optional)',
                'class': 'w-full px-4 py-2.5 rounded-xl border border-slate-200 text-sm focus:outline-none focus:ring-2 focus:ring-orange-500 focus:border-transparent text-slate-900 bg-white placeholder-slate-400',
            }),
        }

    def clean_email(self):
        email = self.cleaned_data.get('email', '').strip().lower()
        if not email:
            raise ValidationError("Email address is required.")
        if User.objects.filter(email__iexact=email).exists():
            raise ValidationError("A user with this email address already exists.")
        return email

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get('password')
        confirm_password = cleaned_data.get('confirm_password')

        if password and confirm_password:
            if password != confirm_password:
                self.add_error('confirm_password', "Passwords do not match.")
            else:
                try:
                    validate_password(password)
                except ValidationError as e:
                    self.add_error('password', e)

        return cleaned_data

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data['password'])
        if commit:
            user.save()
            UserMembership.objects.get_or_create(user=user, defaults={'tier_id': MembershipTier.FREE})
        return user


class UserProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'email']
        widgets = {
            'first_name': forms.TextInput(attrs={
                'class': 'w-full px-4 py-2.5 rounded-xl border border-slate-200 text-sm focus:outline-none focus:ring-2 focus:ring-orange-500 focus:border-transparent text-slate-900 bg-white placeholder-slate-400',
            }),
            'last_name': forms.TextInput(attrs={
                'class': 'w-full px-4 py-2.5 rounded-xl border border-slate-200 text-sm focus:outline-none focus:ring-2 focus:ring-orange-500 focus:border-transparent text-slate-900 bg-white placeholder-slate-400',
            }),
            'email': forms.EmailInput(attrs={
                'class': 'w-full px-4 py-2.5 rounded-xl border border-slate-200 text-sm focus:outline-none focus:ring-2 focus:ring-orange-500 focus:border-transparent text-slate-900 bg-white placeholder-slate-400',
            }),
        }

    def clean_email(self):
        email = self.cleaned_data.get('email', '').strip().lower()
        if not email:
            raise ValidationError("Email is required.")
        if User.objects.filter(email__iexact=email).exclude(pk=self.instance.pk).exists():
            raise ValidationError("This email is already in use by another account.")
        return email


class UserPasswordChangeForm(forms.Form):
    current_password = forms.CharField(
        label="Current Password",
        widget=forms.PasswordInput(attrs={
            'placeholder': '••••••••',
            'class': 'w-full px-4 py-2.5 rounded-xl border border-slate-200 text-sm focus:outline-none focus:ring-2 focus:ring-orange-500 focus:border-transparent text-slate-900 bg-white placeholder-slate-400',
            'autocomplete': 'current-password',
        })
    )
    new_password = forms.CharField(
        label="New Password",
        widget=forms.PasswordInput(attrs={
            'placeholder': 'At least 8 characters',
            'class': 'w-full px-4 py-2.5 rounded-xl border border-slate-200 text-sm focus:outline-none focus:ring-2 focus:ring-orange-500 focus:border-transparent text-slate-900 bg-white placeholder-slate-400',
            'autocomplete': 'new-password',
        })
    )
    confirm_new_password = forms.CharField(
        label="Confirm New Password",
        widget=forms.PasswordInput(attrs={
            'placeholder': 'Re-enter new password',
            'class': 'w-full px-4 py-2.5 rounded-xl border border-slate-200 text-sm focus:outline-none focus:ring-2 focus:ring-orange-500 focus:border-transparent text-slate-900 bg-white placeholder-slate-400',
            'autocomplete': 'new-password',
        })
    )

    def __init__(self, user, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_current_password(self):
        current_password = self.cleaned_data.get('current_password')
        if not self.user.check_password(current_password):
            raise ValidationError("Incorrect current password.")
        return current_password

    def clean(self):
        cleaned_data = super().clean()
        new_password = cleaned_data.get('new_password')
        confirm_new_password = cleaned_data.get('confirm_new_password')

        if new_password and confirm_new_password:
            if new_password != confirm_new_password:
                self.add_error('confirm_new_password', "New passwords do not match.")
            else:
                try:
                    validate_password(new_password, user=self.user)
                except ValidationError as e:
                    self.add_error('new_password', e)

        return cleaned_data


# Admin User Management Forms
class MembershipFormMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields['membership_tier'].initial = membership_for(self.instance).tier_id
        else:
            self.fields['membership_tier'].initial = MembershipTier.FREE

    def save(self, commit=True):
        user = super().save(commit=commit)
        if commit:
            membership = membership_for(user)
            selected_tier = self.cleaned_data.get('membership_tier') or self.fields['membership_tier'].initial
            if membership.tier_id != selected_tier:
                membership.tier_id = selected_tier
                membership.expires_at = None
                if selected_tier == MembershipTier.FREE:
                    membership.clear_limits()
                else:
                    membership.capture_limits(MembershipTier.objects.get(pk=selected_tier))
                membership.save(update_fields=['tier', 'expires_at', 'monthly_search_limit', 'monthly_download_limit'])
        return user


class AdminUserCreateForm(MembershipFormMixin, forms.ModelForm):
    membership_tier = forms.ChoiceField(
        label='Membership tier', choices=MembershipTier.LEVELS, required=False,
        widget=forms.Select(attrs={'class': 'w-full px-4 py-2.5 rounded-xl border border-slate-200 text-sm bg-white'}),
    )
    password = forms.CharField(
        label="Initial Password",
        widget=forms.PasswordInput(attrs={
            'placeholder': 'Set user password (min 8 chars)',
            'class': 'w-full px-4 py-2.5 rounded-xl border border-slate-200 text-sm focus:outline-none focus:ring-2 focus:ring-orange-500 focus:border-transparent text-slate-900 bg-white placeholder-slate-400',
        })
    )
    confirm_password = forms.CharField(
        label="Confirm Password",
        widget=forms.PasswordInput(attrs={
            'placeholder': 'Re-enter initial password',
            'class': 'w-full px-4 py-2.5 rounded-xl border border-slate-200 text-sm focus:outline-none focus:ring-2 focus:ring-orange-500 focus:border-transparent text-slate-900 bg-white placeholder-slate-400',
        })
    )

    class Meta:
        model = User
        fields = ['username', 'email', 'first_name', 'last_name', 'is_active', 'is_staff', 'is_superuser']
        widgets = {
            'username': forms.TextInput(attrs={
                'placeholder': 'e.g. jdoe',
                'class': 'w-full px-4 py-2.5 rounded-xl border border-slate-200 text-sm focus:outline-none focus:ring-2 focus:ring-orange-500 focus:border-transparent text-slate-900 bg-white placeholder-slate-400',
            }),
            'email': forms.EmailInput(attrs={
                'placeholder': 'user@example.com',
                'class': 'w-full px-4 py-2.5 rounded-xl border border-slate-200 text-sm focus:outline-none focus:ring-2 focus:ring-orange-500 focus:border-transparent text-slate-900 bg-white placeholder-slate-400',
            }),
            'first_name': forms.TextInput(attrs={
                'placeholder': 'First Name',
                'class': 'w-full px-4 py-2.5 rounded-xl border border-slate-200 text-sm focus:outline-none focus:ring-2 focus:ring-orange-500 focus:border-transparent text-slate-900 bg-white placeholder-slate-400',
            }),
            'last_name': forms.TextInput(attrs={
                'placeholder': 'Last Name',
                'class': 'w-full px-4 py-2.5 rounded-xl border border-slate-200 text-sm focus:outline-none focus:ring-2 focus:ring-orange-500 focus:border-transparent text-slate-900 bg-white placeholder-slate-400',
            }),
            'is_active': forms.CheckboxInput(attrs={'class': 'h-4 w-4 rounded border-slate-300 text-orange-600 focus:ring-orange-500'}),
            'is_staff': forms.CheckboxInput(attrs={'class': 'h-4 w-4 rounded border-slate-300 text-orange-600 focus:ring-orange-500'}),
            'is_superuser': forms.CheckboxInput(attrs={'class': 'h-4 w-4 rounded border-slate-300 text-orange-600 focus:ring-orange-500'}),
        }

    def clean_email(self):
        email = self.cleaned_data.get('email', '').strip().lower()
        if email and User.objects.filter(email__iexact=email).exists():
            raise ValidationError("A user with this email address already exists.")
        return email

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get('password')
        confirm_password = cleaned_data.get('confirm_password')

        if password and confirm_password:
            if password != confirm_password:
                self.add_error('confirm_password', "Passwords do not match.")
            else:
                try:
                    validate_password(password)
                except ValidationError as e:
                    self.add_error('password', e)

        return cleaned_data

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data['password'])
        if commit:
            user.save()
            selected_tier = self.cleaned_data.get('membership_tier') or MembershipTier.FREE
            tier = MembershipTier.objects.get(pk=selected_tier)
            UserMembership.objects.update_or_create(
                user=user, defaults={
                    'tier': tier,
                    'monthly_search_limit': tier.monthly_search_limit if selected_tier != MembershipTier.FREE else None,
                    'monthly_download_limit': tier.monthly_download_limit if selected_tier != MembershipTier.FREE else None,
                },
            )
        return user


class AdminUserEditForm(MembershipFormMixin, forms.ModelForm):
    membership_tier = forms.ChoiceField(
        label='Membership tier', choices=MembershipTier.LEVELS, required=False,
        widget=forms.Select(attrs={'class': 'w-full px-4 py-2.5 rounded-xl border border-slate-200 text-sm bg-white'}),
    )
    class Meta:
        model = User
        fields = ['username', 'email', 'first_name', 'last_name', 'is_active', 'is_staff', 'is_superuser']
        widgets = {
            'username': forms.TextInput(attrs={
                'class': 'w-full px-4 py-2.5 rounded-xl border border-slate-200 text-sm focus:outline-none focus:ring-2 focus:ring-orange-500 focus:border-transparent text-slate-900 bg-white placeholder-slate-400',
            }),
            'email': forms.EmailInput(attrs={
                'class': 'w-full px-4 py-2.5 rounded-xl border border-slate-200 text-sm focus:outline-none focus:ring-2 focus:ring-orange-500 focus:border-transparent text-slate-900 bg-white placeholder-slate-400',
            }),
            'first_name': forms.TextInput(attrs={
                'class': 'w-full px-4 py-2.5 rounded-xl border border-slate-200 text-sm focus:outline-none focus:ring-2 focus:ring-orange-500 focus:border-transparent text-slate-900 bg-white placeholder-slate-400',
            }),
            'last_name': forms.TextInput(attrs={
                'class': 'w-full px-4 py-2.5 rounded-xl border border-slate-200 text-sm focus:outline-none focus:ring-2 focus:ring-orange-500 focus:border-transparent text-slate-900 bg-white placeholder-slate-400',
            }),
            'is_active': forms.CheckboxInput(attrs={'class': 'h-4 w-4 rounded border-slate-300 text-orange-600 focus:ring-orange-500'}),
            'is_staff': forms.CheckboxInput(attrs={'class': 'h-4 w-4 rounded border-slate-300 text-orange-600 focus:ring-orange-500'}),
            'is_superuser': forms.CheckboxInput(attrs={'class': 'h-4 w-4 rounded border-slate-300 text-orange-600 focus:ring-orange-500'}),
        }

    def clean_email(self):
        email = self.cleaned_data.get('email', '').strip().lower()
        if email and User.objects.filter(email__iexact=email).exclude(pk=self.instance.pk).exists():
            raise ValidationError("This email is already in use by another account.")
        return email


class AdminResetPasswordForm(forms.Form):
    new_password = forms.CharField(
        label="New Password",
        widget=forms.PasswordInput(attrs={
            'placeholder': 'Enter new password (min 8 chars)',
            'class': 'w-full px-4 py-2.5 rounded-xl border border-slate-200 text-sm focus:outline-none focus:ring-2 focus:ring-orange-500 focus:border-transparent text-slate-900 bg-white placeholder-slate-400',
        })
    )
    confirm_new_password = forms.CharField(
        label="Confirm New Password",
        widget=forms.PasswordInput(attrs={
            'placeholder': 'Re-enter new password',
            'class': 'w-full px-4 py-2.5 rounded-xl border border-slate-200 text-sm focus:outline-none focus:ring-2 focus:ring-orange-500 focus:border-transparent text-slate-900 bg-white placeholder-slate-400',
        })
    )

    def __init__(self, target_user, *args, **kwargs):
        self.target_user = target_user
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned_data = super().clean()
        new_password = cleaned_data.get('new_password')
        confirm_new_password = cleaned_data.get('confirm_new_password')

        if new_password and confirm_new_password:
            if new_password != confirm_new_password:
                self.add_error('confirm_new_password', "Passwords do not match.")
            else:
                try:
                    validate_password(new_password, user=self.target_user)
                except ValidationError as e:
                    self.add_error('new_password', e)

        return cleaned_data
