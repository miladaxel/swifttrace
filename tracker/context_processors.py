from django.db import DatabaseError, OperationalError, ProgrammingError


def transfer_permissions(request):
    try:
        from .models import TrackerSettings
        wire_tracker_login_required = TrackerSettings.is_login_required()
    except (DatabaseError, OperationalError, ProgrammingError, Exception):
        wire_tracker_login_required = False

    return {
        'can_view_transfer_records': request.user.is_staff and request.user.has_perm('tracker.view_wiretransfer'),
        'wire_tracker_login_required': wire_tracker_login_required,
    }
