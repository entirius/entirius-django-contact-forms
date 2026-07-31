# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Admin-side queries for Booking. Read-only (calendar owns mutation).

Kept separate from ``booking_service`` — that module powers the public widget
(slot availability + event creation) and must stay focused on the calendar
backend. Mixing admin listing concerns into it would pull ORM filter surface
into a file that does SDK calls.
"""

from datetime import datetime

from django.db.models import Q, QuerySet

from django_contact_forms.models import Booking, Lead


def list_bookings(
    *,
    channel_idx: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    lead_status: str | None = None,
    search: str | None = None,
) -> QuerySet[Booking]:
    """Bounded QuerySet for the admin list view. Caller paginates.

    Validates ``lead_status`` against ``Lead.Status`` before hitting the ORM so
    an unknown value raises ``ValueError`` (mapped to 400) rather than a
    ``FieldError`` 500 that leaks field names.
    """
    if lead_status and lead_status not in Lead.Status.values:
        raise ValueError(f"Unknown lead_status: {lead_status!r}. Allowed: {sorted(Lead.Status.values)}")
    qs = (
        Booking.objects.select_related("contact_form", "contact_form__channel")
        .prefetch_related("contact_form__leads")
        .order_by("-meeting_start")
    )
    if channel_idx:
        qs = qs.filter(contact_form__channel__idx=channel_idx)
    if date_from:
        qs = qs.filter(meeting_start__gte=date_from)
    if date_to:
        qs = qs.filter(meeting_start__lte=date_to)
    if lead_status:
        qs = qs.filter(contact_form__leads__status=lead_status).distinct()
    if search:
        s = search.strip()
        qs = qs.filter(
            Q(contact_form__email__icontains=s) | Q(contact_form__id__icontains=s) | Q(calendar_event_id__icontains=s)
        )
    return qs


def get_booking(*, pk: int) -> Booking:
    return (
        Booking.objects.select_related("contact_form", "contact_form__channel")
        .prefetch_related("contact_form__leads")
        .get(pk=pk)
    )


def resolve_linked_lead(booking: Booking) -> Lead | None:
    """Most recent Lead attached to the same ContactForm, if any.

    ContactForm→Lead is 1:N (a submission can spawn multiple leads over time).
    The admin UI only renders the current state, so we surface the newest.
    Uses the prefetch cache populated by ``list_bookings`` / ``get_booking``
    — iterating in Python here avoids a per-row query.
    """
    leads = list(booking.contact_form.leads.all())
    if not leads:
        return None
    return max(leads, key=lambda lead: lead.contact_date)
