# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Selects the calendar backend implementation from BookingConfig.provider."""

import logging

from django_contact_forms.models import BookingConfig
from django_contact_forms.services.calendar.backends.base import CalendarBackend
from django_contact_forms.services.exceptions import CalendarUnavailableError

logger = logging.getLogger(__name__)


def get_calendar_backend(config: BookingConfig) -> CalendarBackend:
    """Resolve a concrete backend for this channel's configured provider.

    Backends that scope queries to the channel (currently only
    ``LocalOnlyBackend``) read ``config.channel`` directly — no need to pass
    the channel separately. Use ``select_related("channel")`` when loading
    the config if the extra traversal matters in a hot path.
    """
    if config.provider == BookingConfig.Provider.GOOGLE_CALENDAR:
        # Lazy import: only loads the SDK when google_calendar is actually selected.
        # Keeps the module importable when the [bookings] extra is not installed.
        from google_calendar_sdk import CalendarAPIError

        from django_contact_forms.services.calendar.backends.google_calendar import GoogleCalendarBackend

        try:
            return GoogleCalendarBackend(
                credentials_path=config.service_account_credentials_path,
                impersonate_email=config.impersonate_email,
                calendar_id=config.calendar_id,
            )
        except (CalendarAPIError, ValueError) as exc:
            # CalendarAPIError covers CredentialsError (subclass — credentials
            # missing, malformed JSON, impersonation rejected). ValueError covers
            # the SDK's input validation (empty impersonate_email, malformed
            # calendar_id). Both map to a 502 with a generic message; the full
            # exception lands in the SDK / module logger via google_ads_uploader's
            # error_id pattern in the views.
            logger.error("Cannot initialise calendar backend (channel=%s): %s", config.channel.idx, exc)
            raise CalendarUnavailableError("Cannot initialise calendar backend") from exc

    if config.provider == BookingConfig.Provider.LOCAL:
        # No external SDK — no lazy import needed.
        from django_contact_forms.services.calendar.backends.local_only import LocalOnlyBackend

        return LocalOnlyBackend(channel=config.channel)

    raise ValueError(f"Unknown calendar provider: {config.provider!r}")
