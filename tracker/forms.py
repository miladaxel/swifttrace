import uuid
import re
from django import forms


class WireTransferSearchForm(forms.Form):
    uetr = forms.CharField(required=False, max_length=64)
    reference = forms.CharField(required=False, max_length=64)
    date_of_payment = forms.DateField(required=False, input_formats=['%Y-%m-%d'])
    amount = forms.DecimalField(required=False, min_value=0.01, max_digits=18, decimal_places=2)
    currency = forms.CharField(required=False, min_length=3, max_length=3)
    consent = forms.BooleanField(required=True)

    def clean_uetr(self):
        value = self.cleaned_data['uetr'].strip()
        if value:
            if not re.fullmatch(r'[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}', value):
                raise forms.ValidationError('Enter the 36-character UETR in five groups separated by hyphens.')
            try:
                return str(uuid.UUID(value))
            except ValueError:
                raise forms.ValidationError('Enter a valid 36-character UETR.')
        return value

    def clean_reference(self):
        return self.cleaned_data['reference'].strip()

    def clean_currency(self):
        value = self.cleaned_data['currency'].strip().upper()
        if value and not value.isalpha():
            raise forms.ValidationError('Enter a three-letter currency code.')
        return value

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get('uetr') and not cleaned.get('reference'):
            raise forms.ValidationError('Enter a UETR or payment reference.')
        if cleaned.get('reference') and not cleaned.get('uetr') and (
            not cleaned.get('date_of_payment') or cleaned.get('amount') is None
        ):
            raise forms.ValidationError('To search by reference without a UETR, enter the payment date and amount.')
        return cleaned
