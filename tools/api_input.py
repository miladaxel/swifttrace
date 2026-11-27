import json


MAX_IBAN_LENGTH = 128
MAX_NAME_LENGTH = 128
MAX_MT103_TEXT_LENGTH = 128 * 1024
MAX_SMALL_API_BODY_BYTES = 4 * 1024
MAX_MT103_JSON_BODY_BYTES = 160 * 1024


class PayloadTooLarge(Exception):
    pass


def read_api_data(request, max_body_bytes):
    """Accept JSON objects or regular form fields; reject malformed JSON/types."""
    try:
        declared_length = int(request.META.get('CONTENT_LENGTH') or 0)
    except ValueError:
        declared_length = 0
    if declared_length > max_body_bytes:
        raise PayloadTooLarge
    if request.content_type == 'application/json':
        body = request.body
        if len(body) > max_body_bytes:
            raise PayloadTooLarge
        try:
            data = json.loads(body.decode('utf-8'))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
        return data if isinstance(data, dict) else None
    return request.POST
