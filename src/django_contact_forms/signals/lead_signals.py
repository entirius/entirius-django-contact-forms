# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Signal fired when a Lead's status changes (or when one is first created)."""

from django.dispatch import Signal

# Sent by lead_service after a Lead is created or its status transitions.
# Providing args:
#   lead         (Lead)        — the saved Lead instance
#   old_status   (str | None)  — previous status, or None on first creation
#   new_status   (str)         — current status (always present)
#   channel_idx  (str)         — convenience for receivers that don't want to traverse FKs
lead_status_changed = Signal()
