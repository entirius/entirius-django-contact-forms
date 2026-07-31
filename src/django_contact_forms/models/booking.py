# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from django.db import models

from django_contact_forms.models.base_model import BaseModel
from django_contact_forms.models.booking_config import BookingConfig


class Booking(BaseModel):
    """Calendar slot reservation backed by a Google Calendar event.

    Linked 1:1 to the originating ContactForm (FK kept loose so an admin can
    create a manual ContactForm without a Booking). Lead is created separately
    by lead_service so the booking flow stays focused on the calendar concern.
    """

    contact_form = models.OneToOneField("ContactForm", on_delete=models.CASCADE, related_name="booking")
    # Mirrors the BookingConfig.Provider enum — stores which backend was used
    # for this booking. Kept in sync with the config's TextChoices so adding
    # a new provider (e.g. Calendly) automatically makes it a legal value here.
    provider = models.CharField(
        max_length=32,
        choices=BookingConfig.Provider.choices,
        default=BookingConfig.Provider.GOOGLE_CALENDAR,
    )
    calendar_event_id = models.CharField(max_length=255, db_index=True)
    meet_link = models.URLField(blank=True, default="")
    meeting_start = models.DateTimeField()
    meeting_end = models.DateTimeField()
    timezone = models.CharField(max_length=64)

    class Meta:
        indexes = [models.Index(fields=["meeting_start"])]

    def __str__(self) -> str:
        return f"Booking(event={self.calendar_event_id}, start={self.meeting_start.isoformat()})"
