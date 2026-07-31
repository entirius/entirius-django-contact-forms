# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel


class LeadResponse(BaseModel):
    id: int
    contact_form_id: str
    channel_idx: str
    name: str
    email: str
    phone: str
    company: str
    source_type: str
    contact_date: datetime
    message: str
    gclid: str
    hashed_email: str
    attribution_method: str
    campaign_name: str
    source: str
    medium: str
    landing_page: str
    status: str
    deal_value: Decimal | None
    status_changed_at: datetime | None
    notes: str
    ads_conversion_imported: bool
    ads_imported_at: datetime | None


class LeadListResponse(BaseModel):
    count: int
    next: str | None
    previous: str | None
    results: list[LeadResponse]


class LeadStatusCount(BaseModel):
    status: str
    count: int


class LeadSummaryResponse(BaseModel):
    by_status: list[LeadStatusCount]
