def transfer_permissions(request):
    return {'can_view_transfer_records': request.user.is_staff and request.user.has_perm('tracker.view_wiretransfer')}
