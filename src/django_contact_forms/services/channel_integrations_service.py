# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Resolve integration state (google_ads / bookings) for a single channel.

Each flag is the logical AND of the global ContactFormsSettings toggle and the
per-channel config's own ``enabled`` flag. Used by the CMS so it does not have
to read BookingConfig / GoogleAdsConfig directly.
"""

from django_contact_forms.models import BookingConfig, Channel, GoogleAdsConfig
from django_contact_forms.models.contact_forms_settings import (
    is_bookings_enabled,
    is_google_ads_enabled,
)


def get_integrations(*, channel_idx: str) -> dict:
    """Return ``{channel_idx, google_ads_enabled, bookings_enabled}``.

    Raises ``Channel.DoesNotExist`` when the channel is unknown so the caller
    can render 404. Uses ``.exists()`` for the per-channel lookups so a missing
    config row is treated as "disabled" without raising ``DoesNotExist``.
    """
    channel = Channel.objects.get(idx=channel_idx)
    google_ads = is_google_ads_enabled() and GoogleAdsConfig.objects.filter(channel=channel, enabled=True).exists()
    bookings = is_bookings_enabled() and BookingConfig.objects.filter(channel=channel, enabled=True).exists()
    return {
        "channel_idx": channel.idx,
        "google_ads_enabled": google_ads,
        "bookings_enabled": bookings,
    }
