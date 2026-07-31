# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel


class OfflineConversionResponse(BaseModel):
    id: int
    lead_id: int
    channel_idx: str
    conversion_action_id: str
    conversion_action_label: str
    conversion_time: datetime
    conversion_value: Decimal
    currency_code: str
    gclid: str
    hashed_email: str
    status: str
    imported_at: datetime | None
    error_message: str
    attempt_count: int


class OfflineConversionListResponse(BaseModel):
    count: int
    next: str | None
    previous: str | None
    results: list[OfflineConversionResponse]
