from django.urls import path
from . import views

app_name = 'tracker'

urlpatterns = [
    path('wire-transfer/', views.wire_transfer_view, name='wire_transfer'),
    path('track/<int:transfer_id>/', views.tracking_result_view, name='tracking_result'),
    path('private/source-document/<int:document_id>/download/', views.download_source_document, name='download_source_document'),
    path('api/parse-mt103/', views.parse_mt103_api, name='parse_mt103_api'),
]
