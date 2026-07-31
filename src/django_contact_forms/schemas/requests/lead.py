# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from decimal import Decimal

from pydantic import BaseModel, Field


class LeadUpdateRequest(BaseModel):
    """PATCH editable fields. Status is excluded — use the transition endpoint."""

    name: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=32)
    company: str | None = Field(default=None, max_length=255)
    deal_value: Decimal | None = Field(default=None, ge=0)
    notes: str | None = Field(default=None)


class LeadTransitionRequest(BaseModel):
    new_status: str = Field(description="Target status (must satisfy the FSM)")
    deal_value: Decimal | None = Field(default=None, ge=0, description="Required when transitioning to WON")
