# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Database-backed calendar provider — no external service.

Picks a ``BookingConfig.provider = "local"`` channel out of the Google dependency
entirely. Free/busy is derived from existing ``Booking`` rows scoped to the
channel; slot uniqueness is enforced upstream by ``booking_service.create_booking``,
which takes a row lock on the Channel row for the duration of its transaction.

Use this when:

- The tenant doesn't have Google Workspace + domain-wide delegation set up.
- You want a booking widget for an internal/private process (no Meet link
  needed — follow-up happens over email/phone).
- You're running staging or dev and don't want to mock the Google SDK.

The trade-off vs ``GoogleCalendarBackend``: no invites sent to the booker via
Google Calendar, no Meet link, no sync with the operator's real calendar. The
booking confirmation email this module sends (see ``booking_views``) is the
only notification.
"""

from datetime import datetime
from uuid import uuid4

from django_contact_forms.models import Booking, Channel
from django_contact_forms.services.calendar.backends.base import BackendBusyPeriod, BackendEventResult, CalendarBackend


class LocalOnlyBackend(CalendarBackend):
    """Reads free/busy from ``Booking`` rows; creates nothing external."""

    def __init__(self, channel: Channel) -> None:
        self._channel = channel

    def get_busy_periods(self, start: datetime, end: datetime, timezone: str) -> list[BackendBusyPeriod]:
        qs = (
            Booking.objects.filter(
                contact_form__channel=self._channel,
                meeting_start__lt=end,
                meeting_end__gt=start,
            )
            .only("meeting_start", "meeting_end")
            .order_by("meeting_start")
        )
        return [BackendBusyPeriod(start=b.meeting_start, end=b.meeting_end) for b in qs]

    def is_slot_free(self, start: datetime, end: datetime, timezone: str) -> bool:
        return not Booking.objects.filter(
            contact_form__channel=self._channel,
            meeting_start__lt=end,
            meeting_end__gt=start,
        ).exists()

    def create_event(
        self,
        *,
        start: datetime,
        end: datetime,
        summary: str,
        attendee_email: str,
        description: str,
        timezone: str,
    ) -> BackendEventResult:
        # The opaque id stays local to this DB; no external calendar to link.
        return BackendEventResult(event_id=f"local-{uuid4().hex}", meet_link="")
