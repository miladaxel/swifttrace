from django.urls import path
from . import views

app_name = 'tracker'

urlpatterns = [
    path('wire-transfer/', views.wire_transfer_view, name='wire_transfer'),
    path('track/<int:transfer_id>/', views.tracking_result_view, name='tracking_result'),
    path('toggle-login-requirement/', views.toggle_tracker_login_requirement, name='toggle_login_requirement'),
    path('private/source-document/<int:document_id>/download/', views.download_source_document, name='download_source_document'),
    path('track/<int:transfer_id>/statement/download/', views.download_transfer_statement, name='download_transfer_statement'),
    path('api/parse-mt103/', views.parse_mt103_api, name='parse_mt103_api'),
]
