from django.urls import path
from . import views

app_name = 'tools'

urlpatterns = [
    path('iban-validator/', views.iban_validator_view, name='iban_validator'),
    path('sanctions-screener/', views.sanctions_screener_view, name='sanctions_screener'),
    path('correspondent-banks/', views.correspondent_banks_view, name='correspondent_banks'),
    path('arrival-estimator/', views.arrival_estimator_view, name='arrival_estimator'),
    path('document-validator/', views.document_validator_view, name='document_validator'),
    path('api/validate-iban/', views.api_validate_iban, name='api_validate_iban'),
    path('api/screen-sanctions/', views.api_screen_sanctions, name='api_screen_sanctions'),
]
