from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.utils.deconstruct import deconstructible


@deconstructible
class PrivateDocumentStorage(FileSystemStorage):
    """Store source files outside web-served media and disable direct URLs."""

    def __init__(self):
        super().__init__(location=settings.PRIVATE_DOCUMENT_ROOT)

    def url(self, name):
        raise ValueError('Source documents have no public URL.')


private_document_storage = PrivateDocumentStorage()
