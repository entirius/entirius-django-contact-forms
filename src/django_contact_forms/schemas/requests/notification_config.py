# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from pydantic import BaseModel, EmailStr, Field


class FormNotificationConfigCreateRequest(BaseModel):
    channel_id: int = Field(description="Channel primary key", examples=[1])
    form_type: str = Field(
        default="",
        max_length=256,
        description="Form type to match (empty = channel-level default)",
        examples=["complaint"],
    )
    slug: str = Field(
        default="",
        max_length=256,
        description="Form slug to match (empty = type-level default)",
        examples=["contact-us"],
    )
    send_email: bool = Field(
        default=True, description="Whether to send email for matching submissions", examples=[True]
    )
    send_client_copy: bool = Field(
        default=False,
        description="Whether the submitter receives a copy (also gated by body.send_copy)",
        examples=[False],
    )
    recipient_email: EmailStr | str = Field(
        default="",
        description="Override recipient email (empty = use channel admin_email)",
        examples=["support@example.com"],
    )


class FormNotificationConfigUpdateRequest(BaseModel):
    form_type: str | None = Field(
        default=None, max_length=256, description="Form type to match", examples=["complaint"]
    )
    slug: str | None = Field(default=None, max_length=256, description="Form slug to match", examples=["contact-us"])
    send_email: bool | None = Field(default=None, description="Whether to send email", examples=[False])
    send_client_copy: bool | None = Field(
        default=None, description="Whether the submitter receives a copy", examples=[False]
    )
    recipient_email: str | None = Field(
        default=None, description="Override recipient email", examples=["support@example.com"]
    )
