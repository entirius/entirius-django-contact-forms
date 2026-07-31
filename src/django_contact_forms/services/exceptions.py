# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Domain exceptions for the booking + lead + conversions services."""


class BookingDisabledError(Exception):
    """Bookings are off — either the singleton kill-switch or the channel config."""


class InvalidSlotError(Exception):
    """The requested slot violates configured rules (weekend, out-of-hours, in past, too far ahead)."""


class SlotUnavailableError(Exception):
    """The slot was free at validation but became busy by the time we tried to book it."""


class CalendarUnavailableError(Exception):
    """Wraps any failure from the calendar backend."""


class InvalidLeadTransitionError(Exception):
    """A status transition is not allowed by the FSM."""
