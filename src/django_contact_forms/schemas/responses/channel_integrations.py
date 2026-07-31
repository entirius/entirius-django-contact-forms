# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from pydantic import BaseModel


class ChannelIntegrationsResponse(BaseModel):
    """State of optional integrations for a single channel.

    Each flag is ``True`` only when BOTH the global ContactFormsSettings toggle
    AND the per-channel config are enabled. The CMS uses this to gate UI hints
    (e.g. "Conversion will be pushed to Google Ads") without having to read the
    underlying config models.
    """

    channel_idx: str
    google_ads_enabled: bool
    bookings_enabled: bool
