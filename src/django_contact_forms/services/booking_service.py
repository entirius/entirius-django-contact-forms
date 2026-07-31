# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Booking workflow: validate slot, check availability, create calendar event, create ContactForm + Booking + Lead."""

import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from django.db import transaction
from django.utils import timezone

from django_contact_forms.models import (
    Booking,
    BookingConfig,
    BookingTimeWindow,
    Channel,
    ContactForm,
    Lead,
    is_bookings_enabled,
)
from django_contact_forms.services import lead_service
from django_contact_forms.services.calendar.backends.base import BackendBusyPeriod, BackendEventResult
from django_contact_forms.services.calendar.factory import get_calendar_backend
from django_contact_forms.services.calendar.fomo import generate_synthetic_busy_periods, is_weekend
from django_contact_forms.services.exceptions import BookingDisabledError, InvalidSlotError, SlotUnavailableError

# Canonical ContactForm.type value for bookings. Shared with the notification
# service so a typo on one side doesn't silently divert admin emails.
FORM_TYPE_BOOKING = "booking"


def _lock_channel_for_booking(channel: "Channel") -> None:
    """Serialise concurrent bookings per channel. Requires an enclosing
    ``@transaction.atomic`` — ``SELECT ... FOR UPDATE`` outside a transaction
    is a runtime error in Django. The returned row is intentionally unused;
    we only care about the lock, which releases on commit.
    """
    Channel.objects.select_for_update().get(pk=channel.pk)


# Strip CR/LF/control chars from any user-controlled string that flows into a
# Google Calendar event title or description. Newlines in event titles end up
# in email-notification subject lines — phishing primitive.
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


@dataclass
class BookingRequest:
    booking_date: date
    booking_time: time
    name: str
    email: str
    phone: str = ""
    company: str = ""
    message: str = ""
    gclid: str = ""
    utm_source: str = ""
    utm_medium: str = ""
    utm_campaign: str = ""
    landing_page: str = ""
    language: str = ""
    consent: bool = False
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class BookingResult:
    booking: Booking
    lead: Lead
    contact_form: ContactForm


@dataclass(frozen=True)
class Slot:
    start: time
    end: time
    available: bool


@dataclass(frozen=True)
class DaySlots:
    day: date
    slots: list[Slot]


def get_booking_config(*, channel: Channel) -> BookingConfig:
    """Resolve config + assert both kill-switches are on.

    Prefetches ``time_windows`` so subsequent ``config.time_windows.all()`` calls
    in this request hit the prefetch cache instead of re-querying. Eliminates
    ~16 of 17 N+1 queries that otherwise fire across the get_available_slots
    + FOMO + create_booking paths.
    """
    if not is_bookings_enabled():
        raise BookingDisabledError("Bookings are disabled globally (ContactFormsSettings.bookings_enabled=False)")
    try:
        config = BookingConfig.objects.prefetch_related("time_windows").get(channel=channel)
    except BookingConfig.DoesNotExist as exc:
        raise BookingDisabledError(f"Channel {channel.idx} has no BookingConfig") from exc
    if not config.enabled:
        raise BookingDisabledError(f"Bookings disabled for channel {channel.idx}")
    return config


def get_available_slots(*, channel: Channel, date_from: date | None = None, days: int | None = None) -> list[DaySlots]:
    """Return per-day slot availability across the configured horizon.

    Fetches all busy periods for the full horizon in a single backend call,
    then computes slot grids locally. Preserves the ``CalendarBackend.get_busy_periods``
    contract (one wide call per request) and avoids N serial round-trips to Google
    Calendar for an N-day window.
    """
    config = get_booking_config(channel=channel)
    tz = ZoneInfo(config.timezone)
    start_day = date_from or datetime.now(tz).date()
    horizon = min(days or config.days_ahead, config.days_ahead)
    if horizon <= 0:
        return []

    windows = list(config.time_windows.all())
    if not windows:
        return []

    backend = get_calendar_backend(config)
    earliest = min(w.start_time for w in windows)
    latest = max(w.end_time for w in windows)
    window_start = datetime.combine(start_day, earliest, tzinfo=tz)
    window_end = datetime.combine(start_day + timedelta(days=horizon - 1), latest, tzinfo=tz)
    busy = backend.get_busy_periods(window_start, window_end, config.timezone)
    # Add cosmetic synthetic busy periods on top of real ones if FOMO is enabled
    # for this channel. Synthetic periods only filter visibility — is_slot_free
    # still consults the real backend, so a real booking on a synthetic slot
    # always succeeds. See services/calendar/fomo.py.
    busy = busy + generate_synthetic_busy_periods(
        channel_idx=channel.idx,
        config=config,
        windows=windows,
        real_busy=busy,
        start_day=start_day,
        horizon_days=horizon,
    )
    now = datetime.now(tz)

    out: list[DaySlots] = []
    for offset in range(horizon):
        day = start_day + timedelta(days=offset)
        if config.weekdays_only and is_weekend(day):
            continue
        out.append(DaySlots(day=day, slots=_slots_for_day(day, config, tz, now, busy, windows)))
    return out


@transaction.atomic
def create_booking(*, channel: Channel, request: BookingRequest) -> BookingResult:
    """End-to-end booking: validate, check, calendar-insert, persist, send signal.

    Takes a channel-level row lock (``SELECT ... FOR UPDATE`` on the Channel row)
    so concurrent booking requests for the same channel serialise. Even when two
    requests pass ``is_slot_free`` nearly simultaneously, the second one's lock
    acquisition waits until the first transaction commits — at which point the
    newly-persisted Booking makes the second call's ``is_slot_free`` return
    False, and it raises ``SlotUnavailableError``. Works for every backend;
    Google's own 409 handling remains as a second line of defense.
    """
    _lock_channel_for_booking(channel)

    config = get_booking_config(channel=channel)
    tz = ZoneInfo(config.timezone)
    windows = list(config.time_windows.all())
    start_dt, end_dt = _resolve_slot(request.booking_date, request.booking_time, config, tz, windows)

    backend = get_calendar_backend(config)
    if not backend.is_slot_free(start_dt, end_dt, config.timezone):
        raise SlotUnavailableError(f"Slot {start_dt.isoformat()} no longer available")

    event = backend.create_event(
        start=start_dt,
        end=end_dt,
        summary=_render_event_summary(config.event_summary_template, request.name),
        attendee_email=request.email,
        description=_build_event_description(request),
        timezone=config.timezone,
    )

    contact_form, booking = _persist_contact_form_and_booking(channel, config, request, event, start_dt, end_dt)
    lead = _create_lead_for_booking(contact_form, request, event)
    return BookingResult(booking=booking, lead=lead, contact_form=contact_form)


def _resolve_slot(
    booking_date: date,
    booking_time: time,
    config: BookingConfig,
    tz: ZoneInfo,
    windows: list[BookingTimeWindow] | None = None,
) -> tuple[datetime, datetime]:
    if config.weekdays_only and is_weekend(booking_date):
        raise InvalidSlotError(f"{booking_date} is a weekend; weekdays only")

    # Reject sub-minute precision — slot grid is minute-aligned, anything finer
    # is an off-grid hand-crafted POST that should never reach here.
    if booking_time.second or booking_time.microsecond:
        raise InvalidSlotError(f"Booking time {booking_time} must have zero seconds and microseconds")

    duration = timedelta(minutes=config.slot_duration_minutes)
    booking_dt = datetime.combine(booking_date, booking_time, tzinfo=tz)
    slot_end_dt = booking_dt + duration

    # Slot must fit fully inside one of the configured time windows AND start
    # on the slot grid for that window. Full-datetime arithmetic — no .time()
    # rollover when slot crosses midnight.
    if windows is None:
        windows = list(config.time_windows.all())
    in_window = False
    for win in windows:
        win_start_dt = datetime.combine(booking_date, win.start_time, tzinfo=tz)
        win_end_dt = datetime.combine(booking_date, win.end_time, tzinfo=tz)
        if not (win_start_dt <= booking_dt and slot_end_dt <= win_end_dt):
            continue
        # Grid alignment — slot start must land exactly on the per-window grid.
        offset_minutes = int((booking_dt - win_start_dt).total_seconds() // 60)
        if offset_minutes % config.slot_duration_minutes != 0:
            raise InvalidSlotError(
                f"Booking time {booking_time} not aligned to the {config.slot_duration_minutes}-minute grid"
            )
        in_window = True
        break
    if not in_window:
        raise InvalidSlotError(f"Time {booking_time} not within any configured time window")

    if booking_dt < timezone.now():
        raise InvalidSlotError(f"Slot {booking_dt.isoformat()} is in the past")
    horizon_end = (datetime.now(tz) + timedelta(days=config.days_ahead)).date()
    if booking_date > horizon_end:
        raise InvalidSlotError(f"Slot {booking_date} is past the {config.days_ahead}-day horizon")
    return booking_dt, slot_end_dt


def _slots_for_day(
    day: date,
    config: BookingConfig,
    tz: ZoneInfo,
    now: datetime,
    busy: list[BackendBusyPeriod],
    windows: list[BookingTimeWindow],
) -> list[Slot]:
    """Generate slot grid for one day across all configured time windows.

    Each ``BookingTimeWindow`` is iterated independently (no slots span window
    boundaries). ``windows`` is passed in by the caller (already materialised
    once per request) so this helper does not re-hit the DB on every day.
    """
    duration = timedelta(minutes=config.slot_duration_minutes)
    slots: list[Slot] = []
    for window in windows:
        win_start = datetime.combine(day, window.start_time, tzinfo=tz)
        win_end = datetime.combine(day, window.end_time, tzinfo=tz)
        cursor = win_start
        while cursor + duration <= win_end:
            slot_end = cursor + duration
            in_past = cursor < now
            free = (not in_past) and not _overlaps_any(cursor, slot_end, busy)
            slots.append(Slot(start=cursor.time(), end=slot_end.time(), available=free))
            cursor = slot_end
    return slots


def _overlaps_any(start: datetime, end: datetime, busy: list[BackendBusyPeriod]) -> bool:
    return any(b.start < end and b.end > start for b in busy)


def _build_event_description(request: BookingRequest) -> str:
    """Sanitise free-form text before it lands in a calendar invite + email notification."""
    lines = [f"Name: {_sanitize_line(request.name)}", f"Email: {_sanitize_line(request.email)}"]
    if request.phone:
        lines.append(f"Phone: {_sanitize_line(request.phone)}")
    if request.company:
        lines.append(f"Company: {_sanitize_line(request.company)}")
    if request.message:
        lines.append("")
        # Message keeps newlines (multi-line is legitimate in a description) but drops other control chars.
        lines.append(_CONTROL_CHARS.sub("", request.message).replace("\r", ""))
    return "\n".join(lines)


def _render_event_summary(template: str, name: str) -> str:
    """Apply the {name} placeholder. Refuses to leak control chars into the title."""
    return _sanitize_line(template.replace("{name}", name))


def _sanitize_line(value: str) -> str:
    return _CONTROL_CHARS.sub("", value or "")


def _resolve_language(iso2: str | None):
    """Look up django_regional.Language by iso2 (case-insensitive).

    Silent fallback to None when unknown — EmailService._activate_language
    already handles the downstream lang-default chain.
    """
    if not iso2:
        return None
    from django_regional.models import Language

    return Language.objects.filter(iso2__iexact=iso2).first()


def _persist_contact_form_and_booking(
    channel: Channel,
    config: BookingConfig,
    request: BookingRequest,
    event: BackendEventResult,
    start_dt: datetime,
    end_dt: datetime,
) -> tuple[ContactForm, Booking]:
    contact_form = ContactForm.objects.create(
        channel=channel,
        email=request.email,
        language=_resolve_language(request.language),
        type=FORM_TYPE_BOOKING,
        body={
            "name": request.name,
            "phone": request.phone,
            "company": request.company,
            "message": request.message,
            "booking_date": request.booking_date.isoformat(),
            "booking_time": request.booking_time.isoformat(),
            "utm_source": request.utm_source,
            "utm_medium": request.utm_medium,
            "utm_campaign": request.utm_campaign,
            "landing_page": request.landing_page,
            "consent": request.consent,
        },
    )
    booking = Booking.objects.create(
        contact_form=contact_form,
        provider=config.provider,
        calendar_event_id=event.event_id,
        meet_link=event.meet_link,
        meeting_start=start_dt,
        meeting_end=end_dt,
        timezone=config.timezone,
    )
    return contact_form, booking


def _create_lead_for_booking(contact_form: ContactForm, request: BookingRequest, event: BackendEventResult) -> Lead:
    return lead_service.create_lead(
        contact_form=contact_form,
        source_type=Lead.SourceType.CALENDAR,
        name=request.name,
        email=request.email,
        phone=request.phone,
        company=request.company,
        message=request.message,
        gclid=request.gclid,
        attribution_method=(Lead.AttributionMethod.GCLID if request.gclid else Lead.AttributionMethod.UNATTRIBUTED),
        campaign_name=request.utm_campaign,
        source=request.utm_source,
        medium=request.utm_medium,
        landing_page=request.landing_page,
        raw_data=_build_lead_raw_data(request, event),
    )


def _build_lead_raw_data(request: BookingRequest, event: BackendEventResult) -> dict:
    return {
        "language": request.language,
        "consent": request.consent,
        "meet_link": event.meet_link,
        "booking_source": "widget",
        **request.extra,
    }
