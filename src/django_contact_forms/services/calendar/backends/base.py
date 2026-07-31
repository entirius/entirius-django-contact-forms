# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Calendar backend abstract base class. New providers (Calendly, webhook) implement this."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class BackendEventResult:
    event_id: str
    meet_link: str


@dataclass(frozen=True)
class BackendBusyPeriod:
    start: datetime
    end: datetime


class CalendarBackend(ABC):
    """Contract every calendar provider must satisfy. Module owns this — SDKs are pure clients."""

    @abstractmethod
    def get_busy_periods(self, start: datetime, end: datetime, timezone: str) -> list[BackendBusyPeriod]:
        """Return ALL busy intervals in the given window in a single API call.

        Used by ``booking_service.get_available_slots`` to mark a day's slot grid
        in one round-trip instead of one ``is_slot_free`` per slot.
        """
        ...

    @abstractmethod
    def is_slot_free(self, start: datetime, end: datetime, timezone: str) -> bool:
        """Race-condition guard before ``create_event``. ONE call per booking."""
        ...

    @abstractmethod
    def create_event(
        self, *, start: datetime, end: datetime, summary: str, attendee_email: str, description: str, timezone: str
    ) -> BackendEventResult: ...
