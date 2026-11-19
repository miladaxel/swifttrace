from django.urls import path
from . import views

app_name = 'pages'

urlpatterns = [
    path('', views.home_view, name='home'),
    path('for-business/', views.for_business_view, name='for_business'),
    path('company/about/', views.about_view, name='about'),
    path('company/pricing/', views.pricing_view, name='pricing'),
    path('company/scam-alert/', views.scam_alert_view, name='scam_alert'),
]
