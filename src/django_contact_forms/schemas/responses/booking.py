# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from datetime import date, datetime, time
from decimal import Decimal

from pydantic import BaseModel, Field


class BookingCreateResponse(BaseModel):
    status: str = Field(default="booked", examples=["booked"])
    event_id: str = Field(description="Calendar event identifier")
    meet_link: str = Field(description="Conference link (empty if no Meet was attached)")
    meeting_start: datetime
    meeting_end: datetime
    contact_form_id: str = Field(description="Linked ContactForm 12-digit id")
    lead_id: int = Field(description="Linked Lead PK")


class BookingSlot(BaseModel):
    start: time
    end: time
    available: bool


class BookingDay(BaseModel):
    day: date
    slots: list[BookingSlot]


class BookingSlotsResponse(BaseModel):
    timezone: str
    slot_duration_minutes: int
    days: list[BookingDay]


# --- Admin v2 responses -----------------------------------------------------


class LinkedLeadSummary(BaseModel):
    """Compact Lead projection embedded in a Booking admin response.

    The CMS bookings list needs enough to render a status badge + jump to the
    lead detail; it does not need the full LeadResponse payload.
    """

    id: int
    status: str
    name: str
    email: str
    deal_value: Decimal | None
    ads_conversion_imported: bool


class BookingAdminResponse(BaseModel):
    id: int
    contact_form_id: str
    channel_idx: str
    provider: str
    calendar_event_id: str
    meet_link: str
    meeting_start: datetime
    meeting_end: datetime
    timezone: str
    name: str
    email: str
    linked_lead: LinkedLeadSummary | None = None
    created_at: datetime


class BookingListResponse(BaseModel):
    count: int
    next: str | None
    previous: str | None
    results: list[BookingAdminResponse]
