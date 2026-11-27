from django.contrib import admin
from django.conf import settings
from django.urls import path, include

urlpatterns = [
    path('0ab4a2fbfd718a6659c449809d7c3097/', admin.site.urls),
    path('accounts/', include('accounts.urls')),
    path('', include('pages.urls')),
    path('', include('tracker.urls')),
    path('tools/', include('tools.urls')),
    path('', include('dashboard.urls')),
]

if settings.DEBUG:
    urlpatterns.insert(0, path('__debug__/', include('debug_toolbar.urls')))
