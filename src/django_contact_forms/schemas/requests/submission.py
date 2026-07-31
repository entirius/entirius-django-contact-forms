# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from pydantic import BaseModel, EmailStr, Field


class ContactFormSubmitRequest(BaseModel):
    email: EmailStr = Field(description="Submitter email address", examples=["customer@example.com"])
    body: dict | str | None = Field(
        default=None,
        description="Arbitrary form data (JSON object or string)",
        examples=[{"message": "Hello, I need help with my order."}],
    )
    language: str | None = Field(
        default=None, min_length=2, max_length=2, description="ISO 639-1 language code", examples=["en"]
    )
    slug: str | None = Field(
        default=None, max_length=256, description="Form identifier or page slug", examples=["contact-us"]
    )
    form_type: str | None = Field(
        default=None,
        max_length=256,
        description=(
            "Form type code. Resolved against the channel's configured types; "
            "empty or unknown values fall back to the channel default."
        ),
        examples=["product"],
    )
    code: str | None = Field(
        default=None, max_length=256, description="Optional form code (e.g. campaign code)", examples=["SUMMER2025"]
    )
