# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import json
from dataclasses import asdict, dataclass, field
from typing import ClassVar

import marshmallow.validate
from django_utils.api.exceptions import BadRequest
from marshmallow import Schema, post_load
from marshmallow_dataclass import add_schema

# serializers


@dataclass
class DTO:
    def asdict(self) -> dict:
        return asdict(self)


@add_schema
@dataclass
class ContactFormPayload(DTO):
    email: str = field(metadata={"validate": marshmallow.validate.Email(), "required": True})
    code: str | None
    body: str | None = field(metadata={"transform": lambda x: json.dumps(x) if isinstance(x, str) else x})
    language: str | None = field(metadata={"validate": marshmallow.validate.Length(equal=2)})
    slug: str | None = None

    Schema: ClassVar[type[Schema]] = Schema

    @post_load
    def transform_body(self, data, **kwargs):
        try:
            if "body" in data and isinstance(data["body"], str):
                data["body"] = json.loads(data["body"])
            return data
        except json.JSONDecodeError as err:
            raise BadRequest("4011") from err
