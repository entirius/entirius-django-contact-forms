# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class AttachmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description="Attachment primary key", examples=[1])
    name: str | None = Field(description="Original file name", examples=["invoice.pdf"])
    created_at: datetime = Field(description="Upload timestamp", examples=["2025-01-15T10:30:00Z"])
