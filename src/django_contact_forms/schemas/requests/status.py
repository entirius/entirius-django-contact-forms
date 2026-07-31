# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from typing import Literal

from pydantic import BaseModel, Field


class StatusUpdateRequest(BaseModel):
    status: Literal["todo", "in_progress", "done"] = Field(
        description="New processing status", examples=["in_progress"]
    )
