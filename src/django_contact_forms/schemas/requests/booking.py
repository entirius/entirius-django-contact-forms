# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from datetime import date, time

from pydantic import BaseModel, EmailStr, Field, HttpUrl, field_validator


class BookingCreateRequest(BaseModel):
    booking_date: date = Field(description="Slot date in ISO format", examples=["2026-04-25"])
    booking_time: time = Field(description="Slot start time HH:MM (24h)", examples=["10:30"])
    name: str = Field(min_length=1, max_length=255)
    email: EmailStr
    phone: str = Field(default="", max_length=32)
    company: str = Field(default="", max_length=255)
    message: str = Field(default="", max_length=2000)
    gclid: str = Field(default="", max_length=255, description="Google Click ID for attribution")
    utm_source: str = Field(default="", max_length=255)
    utm_medium: str = Field(default="", max_length=255)
    utm_campaign: str = Field(default="", max_length=255)
    # Validated through the field_validator below: empty string passes (the
    # "not supplied" sentinel); any non-empty value MUST parse as an HttpUrl
    # (rejects javascript: / data: / mailto: / arbitrary strings — XSS defense).
    # Stored as a plain str so the rest of the codebase keeps working.
    landing_page: str = Field(default="", max_length=2000)
    language: str = Field(default="", max_length=10)
    consent: bool = Field(default=False, description="GDPR / marketing consent")

    @field_validator("landing_page", mode="before")
    @classmethod
    def _validate_landing_page(cls, value):
        if value in ("", None):
            return ""
        # HttpUrl rejects javascript:, data:, mailto:, etc. Run validation explicitly
        # then return the original string so downstream code sees a plain str.
        HttpUrl(value)  # raises ValidationError on bad URLs
        return value
