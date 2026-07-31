# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Admin API views for OfflineConversionQueue (read + retry).

Per layer rule (django-module-structure.md): NO ORM in views. All query construction
goes through ``queue_service.list_conversions`` / ``get_conversion``. The view's job
is parse → service call → paginate → respond.
"""

from typing import Any

from django.core.exceptions import ObjectDoesNotExist
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import status, viewsets
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework_simplejwt.authentication import JWTAuthentication

from django_contact_forms.api.admin.pagination import AdminPageNumberPagination
from django_contact_forms.api.admin.permissions import IsAdminUser
from django_contact_forms.models import OfflineConversionQueue
from django_contact_forms.schemas.responses.offline_conversion import (
    OfflineConversionListResponse,
    OfflineConversionResponse,
)
from django_contact_forms.services.conversions import queue_service

_ERROR_RESPONSES = {
    400: {"description": "Validation error (e.g. unknown status filter)"},
    401: {"description": "Authentication required"},
    403: {"description": "Permission denied"},
    404: {"description": "Not found"},
}

# Cap admin retries — repeated retries of conversions Google has rejected
# (expired GCLID, malformed currency) inflate `attempt_count` and may
# trigger Ads abuse heuristics on the customer account.
_MAX_RETRY_ATTEMPTS = 5


def _serialize(row: OfflineConversionQueue) -> dict[str, Any]:
    return OfflineConversionResponse(
        id=row.pk,
        lead_id=row.lead_id,
        channel_idx=row.lead.contact_form.channel.idx,
        conversion_action_id=row.conversion_action_id,
        conversion_action_label=row.conversion_action_label,
        conversion_time=row.conversion_time,
        conversion_value=row.conversion_value,
        currency_code=row.currency_code,
        gclid=row.gclid,
        hashed_email=row.hashed_email,
        status=row.status,
        imported_at=row.imported_at,
        error_message=row.error_message,
        attempt_count=row.attempt_count,
    ).model_dump()


@extend_schema_view(
    list=extend_schema(tags=["Offline Conversions"]),
    retrieve=extend_schema(tags=["Offline Conversions"]),
    retry=extend_schema(tags=["Offline Conversions"]),
)
class OfflineConversionViewSet(viewsets.ViewSet):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAdminUser]

    @extend_schema(
        summary="List offline conversions",
        parameters=[
            OpenApiParameter(name="channel", type=str),
            OpenApiParameter(name="status", type=str, description="pending, imported, failed, skipped"),
            OpenApiParameter(name="page", type=int),
            OpenApiParameter(name="page_size", type=int),
        ],
        responses={200: OfflineConversionListResponse, **_ERROR_RESPONSES},
    )
    def list(self, request: Request, **kwargs) -> Response:
        try:
            qs = queue_service.list_conversions(
                channel_idx=request.query_params.get("channel") or None,
                status=request.query_params.get("status") or None,
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        paginator = AdminPageNumberPagination()
        page = paginator.paginate_queryset(qs, request)
        return Response(
            OfflineConversionListResponse(
                count=paginator.page.paginator.count,
                next=paginator.get_next_link(),
                previous=paginator.get_previous_link(),
                results=[_serialize(row) for row in page],
            ).model_dump()
        )

    @extend_schema(
        summary="Retrieve offline conversion",
        parameters=[OpenApiParameter(name="pk", location=OpenApiParameter.PATH, type=int)],
        responses={200: OfflineConversionResponse, **_ERROR_RESPONSES},
    )
    def retrieve(self, request: Request, pk: int, **kwargs) -> Response:
        try:
            row = queue_service.get_conversion(pk=int(pk))
        except (OfflineConversionQueue.DoesNotExist, ObjectDoesNotExist):
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(_serialize(row))

    @extend_schema(
        summary="Retry a failed conversion",
        description=(
            "Resets the row to PENDING for the next worker run. Useful after fixing a config "
            "error. Refused once attempt_count reaches the configured maximum."
        ),
        parameters=[OpenApiParameter(name="pk", location=OpenApiParameter.PATH, type=int)],
        responses={200: OfflineConversionResponse, **_ERROR_RESPONSES},
    )
    def retry(self, request: Request, pk: int, **kwargs) -> Response:
        try:
            row = queue_service.get_conversion(pk=int(pk))
        except (OfflineConversionQueue.DoesNotExist, ObjectDoesNotExist):
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        if (row.attempt_count or 0) >= _MAX_RETRY_ATTEMPTS:
            return Response(
                {
                    "error": "RETRY_LIMIT_EXCEEDED",
                    "attempt_count": row.attempt_count,
                    "max_attempts": _MAX_RETRY_ATTEMPTS,
                    "message": "Retry refused — fix the underlying configuration before retrying again.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        queue_service.reset_to_pending(queue_id=row.pk, actor=request.user.username)
        row.refresh_from_db()
        return Response(_serialize(row))
