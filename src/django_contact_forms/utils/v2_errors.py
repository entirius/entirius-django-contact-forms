# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Shared error helpers for v2 API views.

``raise_pydantic_as_drf`` converts a Pydantic ``ValidationError`` into a DRF
``ValidationError`` so the v2 exception handler formats it into the structured
``{ error, message, debug_id, details[] }`` response that the CMS
``useFormErrors`` composable parses for field-level error display.
"""

import logging
import uuid

from pydantic import ValidationError as PydanticValidationError
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.response import Response

logger = logging.getLogger(__name__)


def raise_pydantic_as_drf(exc: PydanticValidationError) -> None:
    """Convert Pydantic ValidationError to DRF ValidationError (matches agreements pattern)."""
    detail: dict[str, list[str]] = {}
    for error in exc.errors():
        field = ".".join(str(loc) for loc in error["loc"]) or "non_field_errors"
        detail.setdefault(field, []).append(error["msg"])
    raise DRFValidationError(detail)


def internal_error_response(exc: Exception, *, public_message: str = "Internal server error") -> Response:
    """Generate a unique error_id, log the full exception with it, return a sanitised 5xx body.

    Use this in `except Exception` blocks where the original message may carry
    SDK error details, file paths, refresh-token error fragments, customer IDs,
    etc. Returns 500. For 502 (upstream provider) supply a domain-specific
    public_message like 'Calendar provider unavailable'.
    """
    error_id = uuid.uuid4().hex[:12]
    logger.exception("[error_id=%s] %s", error_id, exc)
    return Response({"detail": f"{public_message} [{error_id}]"}, status=500)


def upstream_unavailable_response(exc: Exception, *, public_message: str) -> Response:
    """Same shape as internal_error_response but for 502 (upstream / provider failure)."""
    error_id = uuid.uuid4().hex[:12]
    logger.error("[error_id=%s] upstream unavailable: %s", error_id, exc)
    return Response({"detail": f"{public_message} [{error_id}]"}, status=502)
