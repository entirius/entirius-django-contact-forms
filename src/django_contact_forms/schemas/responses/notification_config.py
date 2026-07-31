# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from pydantic import BaseModel, ConfigDict, Field


class FormNotificationConfigResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description="Config primary key", examples=[1])
    channel_id: int = Field(description="Channel primary key", examples=[1])
    channel_idx: str = Field(description="Channel identifier", examples=["default-europe"])
    form_type: str = Field(description="Form type filter (empty = channel-level default)", examples=["complaint"])
    slug: str = Field(description="Form slug filter (empty = type-level default)", examples=["contact-us"])
    send_email: bool = Field(description="Whether to send email for matching submissions", examples=[True])
    send_client_copy: bool = Field(
        description="Whether the submitter receives a copy (also gated by body.send_copy)", examples=[False]
    )
    recipient_email: str = Field(
        description="Override recipient email (empty = channel admin_email)", examples=["support@example.com"]
    )


class FormNotificationConfigListResponse(BaseModel):
    count: int = Field(description="Total number of results", examples=[5])
    next: str | None = Field(description="URL to next page", examples=[None])
    previous: str | None = Field(description="URL to previous page", examples=[None])
    results: list[dict] = Field(description="List of notification configs")
