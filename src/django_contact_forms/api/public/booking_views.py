# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Public booking endpoints — slot listing + booking creation."""

from datetime import date, datetime

from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from pydantic import ValidationError
from rest_framework import status, viewsets
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response

from django_contact_forms.api.public.authentication import BookingAPIKeyAuthentication
from django_contact_forms.api.public.throttling import BookingThrottle
from django_contact_forms.schemas.requests.booking import BookingCreateRequest
from django_contact_forms.schemas.responses.booking import (
    BookingCreateResponse,
    BookingDay,
    BookingSlot,
    BookingSlotsResponse,
)
from django_contact_forms.services import booking_notification_service, booking_service
from django_contact_forms.services.booking_service import BookingRequest
from django_contact_forms.services.exceptions import (
    BookingDisabledError,
    CalendarUnavailableError,
    InvalidSlotError,
    SlotUnavailableError,
)
from django_contact_forms.utils.v2_errors import raise_pydantic_as_drf, upstream_unavailable_response

_PUBLIC_ERRORS = {
    400: {"description": "Validation or slot rule error"},
    401: {"description": "X-API-KEY missing or invalid"},
    409: {"description": "Slot taken between validation and booking"},
    502: {"description": "Calendar provider unavailable"},
}


@extend_schema_view(list=extend_schema(tags=["Bookings (public)"]), create=extend_schema(tags=["Bookings (public)"]))
class BookingViewSet(viewsets.ViewSet):
    """X-API-KEY authentication scoped to ``booking`` keys (defense in depth)."""

    authentication_classes = [BookingAPIKeyAuthentication]
    permission_classes = [AllowAny]
    throttle_classes = [BookingThrottle]

    @extend_schema(
        summary="List available booking slots",
        description="Returns per-day slot grids over the configured horizon. ?date_from and ?days narrow the window.",
        parameters=[
            OpenApiParameter(name="date_from", type=str, description="ISO date (YYYY-MM-DD)"),
            OpenApiParameter(name="days", type=int, description="Number of days to scan (capped by config)"),
        ],
        responses={200: BookingSlotsResponse, **_PUBLIC_ERRORS},
    )
    def list(self, request: Request, channel_idx: str, **kwargs) -> Response:
        channel = request.auth  # APIKeyAuthentication returns the Channel as auth
        date_from = _parse_date(request.query_params.get("date_from"))
        days_str = request.query_params.get("days")
        try:
            days = int(days_str) if days_str else None
        except ValueError:
            return Response({"detail": "Invalid 'days' parameter."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            day_grids = booking_service.get_available_slots(channel=channel, date_from=date_from, days=days)
        except BookingDisabledError as exc:
            # 400 with a static message — operator-facing UI surfaces it; no upstream secrets here.
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except CalendarUnavailableError as exc:
            return upstream_unavailable_response(exc, public_message="Calendar provider unavailable")

        config = channel.booking_config
        return Response(
            BookingSlotsResponse(
                timezone=config.timezone,
                slot_duration_minutes=config.slot_duration_minutes,
                days=[
                    BookingDay(
                        day=grid.day,
                        slots=[BookingSlot(start=s.start, end=s.end, available=s.available) for s in grid.slots],
                    )
                    for grid in day_grids
                ],
            ).model_dump(mode="json")
        )

    @extend_schema(
        summary="Create a booking",
        description="Validates the slot, checks availability one more time, creates the calendar event, and persists ContactForm + Booking + Lead in one transaction.",
        request=BookingCreateRequest,
        responses={201: BookingCreateResponse, **_PUBLIC_ERRORS},
    )
    def create(self, request: Request, channel_idx: str, **kwargs) -> Response:
        channel = request.auth
        try:
            payload = BookingCreateRequest(**request.data)
        except ValidationError as exc:
            raise_pydantic_as_drf(exc)

        booking_request = BookingRequest(
            booking_date=payload.booking_date,
            booking_time=payload.booking_time,
            name=payload.name,
            email=payload.email,
            phone=payload.phone,
            company=payload.company,
            message=payload.message,
            gclid=payload.gclid,
            utm_source=payload.utm_source,
            utm_medium=payload.utm_medium,
            utm_campaign=payload.utm_campaign,
            landing_page=payload.landing_page,
            language=payload.language,
            consent=payload.consent,
        )

        try:
            result = booking_service.create_booking(channel=channel, request=booking_request)
        except BookingDisabledError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except InvalidSlotError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except SlotUnavailableError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        except CalendarUnavailableError as exc:
            return upstream_unavailable_response(exc, public_message="Calendar provider unavailable")

        # Notification fan-out owned by the service layer; failures there
        # never turn a successful booking into a 5xx.
        booking_notification_service.send_booking_notifications(channel=channel, result=result)

        return Response(
            BookingCreateResponse(
                event_id=result.booking.calendar_event_id,
                meet_link=result.booking.meet_link,
                meeting_start=result.booking.meeting_start,
                meeting_end=result.booking.meeting_end,
                contact_form_id=result.contact_form.pk,
                lead_id=result.lead.pk,
            ).model_dump(mode="json"),
            status=status.HTTP_201_CREATED,
        )


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None
