# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from pydantic import BaseModel, ConfigDict, Field


class FormTypeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str = Field(description="Form type code", examples=["product"])
    label: str = Field(description="Human-readable label", examples=["Product enquiry"])
    is_default: bool = Field(description="Used when a submission carries no/unknown type", examples=[False])


class FormTypeListResponse(BaseModel):
    results: list[FormTypeResponse] = Field(description="Configured form types for the channel")
