# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Outbound queue of click-conversions to push to Google Ads."""

from django.db import models

from django_contact_forms.models.base_model import BaseModel


class OfflineConversionQueue(BaseModel):
    """One row per (Lead, conversion_action_id). Drained by the Celery worker."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        IMPORTED = "imported", "Imported"
        FAILED = "failed", "Failed"
        SKIPPED = "skipped", "Skipped"  # no gclid + no hashed_email — Google Ads can't match

    class Environment(models.TextChoices):
        WEB = "WEB", "Web"
        APP = "APP", "App"

    lead = models.ForeignKey("Lead", on_delete=models.CASCADE, related_name="offline_conversions")

    conversion_action_id = models.CharField(max_length=32, help_text="Google Ads conversion action ID (digits only).")
    conversion_action_label = models.CharField(
        max_length=64, help_text="Human label for admin (e.g. 'Meeting Booked', 'Won Deal')."
    )
    conversion_time = models.DateTimeField()
    conversion_value = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    currency_code = models.CharField(max_length=3, default="EUR")
    conversion_environment = models.CharField(max_length=8, choices=Environment.choices, default=Environment.WEB)

    # Identifiers carried forward from the Lead at enqueue time (frozen so later edits don't affect the upload)
    gclid = models.CharField(max_length=255, blank=True, default="")
    hashed_email = models.CharField(max_length=64, blank=True, default="")

    # Lifecycle
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING, db_index=True)
    imported_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True, default="")
    attempt_count = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["lead", "conversion_action_id"], name="uniq_lead_conversion_action"),
        ]
        indexes = [models.Index(fields=["-created_at"])]
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return (
            f"OfflineConversionQueue(lead={self.lead_id}, action={self.conversion_action_label}, status={self.status})"
        )
