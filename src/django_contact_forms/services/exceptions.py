# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Domain exceptions for the booking + lead + conversions services."""


class ClientError(Exception):
    """A refusal whose message this module wrote for the API client.

    A view answers with ``exc.client_message``, never with ``str(exc)``: only these classes carry text meant for
    a response, so an exception from a lower layer cannot reach a client by being caught too broadly.
    """

    def __init__(self, client_message: str) -> None:
        super().__init__(client_message)
        self.client_message = client_message


class InvalidFilterError(ClientError, ValueError):
    """A list filter or ordering value the service does not accept (still a ``ValueError`` for direct callers)."""


class BookingDisabledError(Exception):
    """Bookings are off — either the singleton kill-switch or the channel config.

    Not a ``ClientError``: the message names internal settings, the public API answers with its own text.
    """


class InvalidSlotError(ClientError):
    """The requested slot violates configured rules (weekend, out-of-hours, in past, too far ahead)."""


class SlotUnavailableError(ClientError):
    """The slot was free at validation but became busy by the time we tried to book it."""


class CalendarUnavailableError(Exception):
    """Wraps any failure from the calendar backend."""


class InvalidLeadTransitionError(Exception):
    """A status transition is not allowed by the FSM."""
