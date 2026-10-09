# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Admin API views for Booking (read-only — calendar owns mutation)."""

from datetime import datetime
from typing import Any

from django.core.exceptions import ObjectDoesNotExist
from django.utils.dateparse import parse_datetime
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import status, viewsets
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework_simplejwt.authentication import JWTAuthentication

from django_contact_forms.api.admin.pagination import AdminPageNumberPagination
from django_contact_forms.api.admin.permissions import IsAdminUser
from django_contact_forms.models import Booking
from django_contact_forms.schemas.responses.booking import (
    BookingAdminResponse,
    BookingListResponse,
    LinkedLeadSummary,
)
from django_contact_forms.services import booking_admin_service

_ERROR_RESPONSES = {
    400: {"description": "Validation error (e.g. unknown lead_status filter)"},
    401: {"description": "Authentication required"},
    403: {"description": "Permission denied"},
    404: {"description": "Not found"},
}


def _serialize(booking: Booking) -> dict[str, Any]:
    cf = booking.contact_form
    body = cf.body if isinstance(cf.body, dict) else {}
    lead = booking_admin_service.resolve_linked_lead(booking)
    linked = (
        LinkedLeadSummary(
            id=lead.pk,
            status=lead.status,
            name=lead.name,
            email=lead.email,
            deal_value=lead.deal_value,
            ads_conversion_imported=lead.ads_conversion_imported,
        )
        if lead
        else None
    )
    return BookingAdminResponse(
        id=booking.pk,
        contact_form_id=cf.pk,
        channel_idx=cf.channel.idx,
        provider=booking.provider,
        calendar_event_id=booking.calendar_event_id,
        meet_link=booking.meet_link,
        meeting_start=booking.meeting_start,
        meeting_end=booking.meeting_end,
        timezone=booking.timezone,
        name=str(body.get("name", "") or ""),
        email=cf.email,
        linked_lead=linked,
        created_at=booking.created_at,
    ).model_dump()


def _parse_datetime_param(raw: str | None) -> datetime | None:
    """Accept ISO-8601 with or without time. Return None on empty/invalid.

    A 400 is preferable to silently dropping an invalid filter — raise
    ValueError so the caller can surface it.
    """
    if not raw:
        return None
    parsed = parse_datetime(raw)
    if parsed is not None:
        return parsed
    # Accept bare date ("2026-04-20") by delegating to fromisoformat
    try:
        return datetime.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError(f"Invalid datetime: {raw!r}") from exc


@extend_schema_view(
    list=extend_schema(tags=["Bookings"]),
    retrieve=extend_schema(tags=["Bookings"]),
)
class BookingViewSet(viewsets.ViewSet):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAdminUser]
    access_area = "contact_forms.submissions"

    @extend_schema(
        summary="List bookings",
        description=(
            "Paginated list of calendar bookings. Filterable by channel, meeting_start "
            "date range, and linked-lead status. Search matches contact form email, id, "
            "or calendar event id."
        ),
        parameters=[
            OpenApiParameter(name="channel", type=str),
            OpenApiParameter(name="date_from", type=str, description="ISO-8601 datetime or date"),
            OpenApiParameter(name="date_to", type=str, description="ISO-8601 datetime or date"),
            OpenApiParameter(name="lead_status", type=str),
            OpenApiParameter(name="search", type=str),
            OpenApiParameter(name="page", type=int),
            OpenApiParameter(name="page_size", type=int),
        ],
        responses={200: BookingListResponse, **_ERROR_RESPONSES},
    )
    def list(self, request: Request, **kwargs) -> Response:
        try:
            qs = booking_admin_service.list_bookings(
                channel_idx=request.query_params.get("channel") or None,
                date_from=_parse_datetime_param(request.query_params.get("date_from")),
                date_to=_parse_datetime_param(request.query_params.get("date_to")),
                lead_status=request.query_params.get("lead_status") or None,
                search=request.query_params.get("search") or None,
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        paginator = AdminPageNumberPagination()
        page = paginator.paginate_queryset(qs, request)
        return Response(
            BookingListResponse(
                count=paginator.page.paginator.count,
                next=paginator.get_next_link(),
                previous=paginator.get_previous_link(),
                results=[_serialize(booking) for booking in page],
            ).model_dump()
        )

    @extend_schema(
        summary="Retrieve booking",
        parameters=[OpenApiParameter(name="pk", location=OpenApiParameter.PATH, type=int)],
        responses={200: BookingAdminResponse, **_ERROR_RESPONSES},
    )
    def retrieve(self, request: Request, pk: int, **kwargs) -> Response:
        try:
            booking = booking_admin_service.get_booking(pk=int(pk))
        except (Booking.DoesNotExist, ObjectDoesNotExist):
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(_serialize(booking))
