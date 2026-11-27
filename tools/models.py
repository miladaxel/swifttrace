from django.db import models


class PublicProcessingRateWindow(models.Model):
    lookup_key = models.CharField(max_length=64)
    window_start = models.DateTimeField()
    attempts = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['lookup_key', 'window_start'], name='unique_public_processing_window')]
        indexes = [models.Index(fields=['window_start'], name='public_processing_window_idx')]
