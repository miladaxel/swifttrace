from django.urls import path
from . import views

app_name = 'accounts'

urlpatterns = [
    # Auth URLs
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('register/', views.register_view, name='register'),
    path('profile/', views.profile_view, name='profile'),
    path('change-password/', views.change_password_view, name='change_password'),
    path('plans/<str:level>/start/', views.start_plan_purchase_view, name='start_plan_purchase'),
    path('purchases/', views.plan_purchase_history_view, name='plan_purchase_history'),
    path('purchases/<uuid:purchase_id>/', views.plan_purchase_view, name='plan_purchase'),
    path('purchases/<uuid:purchase_id>/qr/', views.purchase_qr_view, name='purchase_qr'),
    path('purchases/<uuid:purchase_id>/receipt/', views.purchase_receipt_view, name='purchase_receipt'),

    # User Management URLs (Staff / Admin)
    path('users/', views.user_list_view, name='user_list'),
    path('users/payment-requests/', views.purchase_review_list_view, name='purchase_review_list'),
    path('users/payment-requests/<uuid:purchase_id>/', views.purchase_review_detail_view, name='purchase_review_detail'),
    path('users/payment-requests/<uuid:purchase_id>/review/', views.purchase_review_action_view, name='purchase_review_action'),
    path('users/create/', views.user_create_view, name='user_create'),
    path('users/<int:user_id>/edit/', views.user_edit_view, name='user_edit'),
    path('users/<int:user_id>/password/', views.user_password_view, name='user_password'),
    path('users/<int:user_id>/toggle-status/', views.user_toggle_status_view, name='user_toggle_status'),
    path('users/<int:user_id>/delete/', views.user_delete_view, name='user_delete'),
]
