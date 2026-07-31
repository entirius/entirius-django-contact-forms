# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""GoogleCalendarBackend — adapts google-calendar-sdk to the local CalendarBackend ABC."""

import logging
from datetime import datetime

from google_calendar_sdk import CalendarAPIError, GoogleCalendarClient

from django_contact_forms.services.calendar.backends.base import BackendBusyPeriod, BackendEventResult, CalendarBackend
from django_contact_forms.services.exceptions import CalendarUnavailableError

logger = logging.getLogger(__name__)


class GoogleCalendarBackend(CalendarBackend):
    def __init__(self, *, credentials_path: str, impersonate_email: str, calendar_id: str) -> None:
        self._client = GoogleCalendarClient(
            credentials_path=credentials_path, impersonate_email=impersonate_email, calendar_id=calendar_id or "primary"
        )

    def get_busy_periods(self, start: datetime, end: datetime, timezone: str) -> list[BackendBusyPeriod]:
        try:
            sdk_busy = self._client.get_busy_periods(start, end, timezone)
        except CalendarAPIError as exc:
            logger.error("calendar get_busy_periods failed: %s", exc)
            raise CalendarUnavailableError("Calendar provider unavailable") from exc
        return [BackendBusyPeriod(start=p.start, end=p.end) for p in sdk_busy]

    def is_slot_free(self, start: datetime, end: datetime, timezone: str) -> bool:
        try:
            return self._client.is_slot_free(start, end, timezone)
        except CalendarAPIError as exc:
            logger.error("calendar is_slot_free failed: %s", exc)
            raise CalendarUnavailableError("Calendar provider unavailable") from exc

    def create_event(
        self, *, start: datetime, end: datetime, summary: str, attendee_email: str, description: str, timezone: str
    ) -> BackendEventResult:
        try:
            event = self._client.create_event(
                start=start,
                end=end,
                summary=summary,
                attendee_email=attendee_email,
                description=description,
                timezone=timezone,
                create_meet_link=True,
            )
        except CalendarAPIError as exc:
            logger.error("calendar create_event failed: %s", exc)
            raise CalendarUnavailableError("Calendar provider unavailable") from exc
        # SDK 1.0.1: meet_link is `str | None` (was empty-string for missing).
        return BackendEventResult(event_id=event.event_id, meet_link=event.meet_link or "")
