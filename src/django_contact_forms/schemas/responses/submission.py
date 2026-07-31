# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from django_contact_forms.schemas.responses.attachment import AttachmentResponse


class ContactFormResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str = Field(description="12-digit contact form identifier", examples=["384729105638"])
    email: str = Field(description="Submitter email address", examples=["customer@example.com"])
    channel_idx: str = Field(description="Channel identifier", examples=["default-europe"])
    slug: str | None = Field(description="Form identifier or page slug", examples=["contact-us"])
    type: str | None = Field(description="Form type or category", examples=["complaint"])
    code: str | None = Field(description="Optional form code", examples=["SUMMER2025"])
    language: str | None = Field(description="ISO 639-1 language code", examples=["en"])
    body: Any | None = Field(description="Arbitrary form data (JSON)", examples=[{"message": "Hello"}])
    status: str = Field(description="Processing status (todo, in_progress, done)", examples=["todo"])
    attachments: list[AttachmentResponse] = Field(default_factory=list, description="List of file attachments")
    created_at: datetime = Field(description="Submission timestamp", examples=["2025-01-15T10:30:00Z"])


class ContactFormListResponse(BaseModel):
    count: int = Field(description="Total number of results", examples=[42])
    next: str | None = Field(
        description="URL to next page",
        examples=["http://localhost:8000/api/contact-forms/v2/admin/submissions/?page=2"],
    )
    previous: str | None = Field(description="URL to previous page", examples=[None])
    results: list[dict] = Field(description="List of contact form submissions")
