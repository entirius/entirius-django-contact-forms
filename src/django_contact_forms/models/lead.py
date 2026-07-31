# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Lead — sales pipeline entity created from a ContactForm submission or Booking."""

from django.db import models
from django.utils import timezone

from django_contact_forms.models.base_model import BaseModel


class Lead(BaseModel):
    """A contact who became a sales prospect. Tracks attribution + commercial outcome."""

    class SourceType(models.TextChoices):
        CALENDAR = "calendar", "Calendar"
        FORM = "form", "Contact form"
        WHATSAPP = "whatsapp", "WhatsApp"
        EMAIL = "email", "Email"
        PHONE = "phone", "Phone"
        OTHER = "other", "Other"

    class AttributionMethod(models.TextChoices):
        GCLID = "gclid", "Google Click ID"
        ENHANCED = "enhanced", "Enhanced (hashed email)"
        TIME_PROXIMITY = "time_proximity", "Time-based proximity"
        MANUAL = "manual", "Manual"
        UNATTRIBUTED = "unattributed", "Unattributed"

    class Status(models.TextChoices):
        NEW = "new", "New"
        CONTACTED = "contacted", "Contacted"
        QUALIFIED = "qualified", "Qualified"
        UNQUALIFIED = "unqualified", "Unqualified"
        WON = "won", "Won"
        LOST = "lost", "Lost"

    contact_form = models.ForeignKey("ContactForm", on_delete=models.CASCADE, related_name="leads")

    # Contact
    name = models.CharField(max_length=255, blank=True, default="")
    email = models.EmailField(blank=True, default="")
    phone = models.CharField(max_length=32, blank=True, default="")
    company = models.CharField(max_length=255, blank=True, default="")

    # Source
    source_type = models.CharField(max_length=16, choices=SourceType.choices, default=SourceType.OTHER, db_index=True)
    contact_date = models.DateTimeField(default=timezone.now, db_index=True)
    message = models.TextField(blank=True, default="")

    # Attribution (Google Ads matching)
    gclid = models.CharField(max_length=255, blank=True, default="", db_index=True)
    hashed_email = models.CharField(
        max_length=64, blank=True, default="", help_text="SHA-256 hex of lower-cased email (enhanced fallback)."
    )
    attribution_method = models.CharField(
        max_length=16, choices=AttributionMethod.choices, default=AttributionMethod.UNATTRIBUTED
    )
    campaign_name = models.CharField(max_length=255, blank=True, default="", db_index=True)
    source = models.CharField(max_length=255, blank=True, default="")
    medium = models.CharField(max_length=255, blank=True, default="")
    landing_page = models.URLField(blank=True, default="")

    # Lifecycle
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.NEW, db_index=True)
    deal_value = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    status_changed_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True, default="")

    # Google Ads import tracking
    ads_conversion_imported = models.BooleanField(default=False)
    ads_imported_at = models.DateTimeField(null=True, blank=True)

    # Raw payload (UTM, consent, language, anything that doesn't deserve a column)
    raw_data = models.JSONField(default=dict, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["-contact_date"]),
            # Common admin filter: ?status=new (or ?status=qualified) ordered by -contact_date.
            # Without this Postgres seq-scans Lead at 10k+ rows.
            models.Index(fields=["status", "-contact_date"]),
        ]
        ordering = ["-contact_date"]

    def __str__(self) -> str:
        return f"Lead(id={self.pk}, status={self.status}, email={self.email})"
