# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Booking service: kill-switch, slot validation, end-to-end create with mocked backend."""

from datetime import date, datetime, time, timedelta
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest
from django.utils import timezone

from django_contact_forms.models import Booking, ContactForm, Lead, OfflineConversionQueue
from django_contact_forms.services import booking_service
from django_contact_forms.services.booking_service import BookingRequest, _resolve_slot
from django_contact_forms.services.calendar.backends.base import BackendEventResult
from django_contact_forms.services.exceptions import BookingDisabledError, InvalidSlotError, SlotUnavailableError
from tests.factories import BookingConfigFactory, ChannelFactory, enable_global_settings


def _next_weekday_at(hour: int) -> datetime:
    """Return a future datetime guaranteed to land on a weekday at the given hour (Europe/Warsaw)."""
    tz = ZoneInfo("Europe/Warsaw")
    candidate = datetime.now(tz).replace(hour=hour, minute=0, second=0, microsecond=0) + timedelta(days=2)
    while candidate.weekday() >= 5:
        candidate += timedelta(days=1)
    return candidate


@pytest.mark.django_db
def test_get_booking_config_disabled_when_global_off():
    enable_global_settings(bookings=False)
    channel = ChannelFactory()
    BookingConfigFactory(channel=channel)
    with pytest.raises(BookingDisabledError):
        booking_service.get_booking_config(channel=channel)


@pytest.mark.django_db
def test_get_booking_config_disabled_when_no_config():
    enable_global_settings(bookings=True)
    channel = ChannelFactory()  # no BookingConfig
    with pytest.raises(BookingDisabledError):
        booking_service.get_booking_config(channel=channel)


@pytest.mark.django_db
def test_get_booking_config_disabled_when_channel_off():
    enable_global_settings(bookings=True)
    channel = ChannelFactory()
    BookingConfigFactory(channel=channel, enabled=False)
    with pytest.raises(BookingDisabledError):
        booking_service.get_booking_config(channel=channel)


@pytest.mark.django_db
def test_create_booking_rejects_weekend_slot():
    enable_global_settings(bookings=True)
    channel = ChannelFactory()
    BookingConfigFactory(channel=channel)
    # Find a Saturday in the future
    tz = ZoneInfo("Europe/Warsaw")
    future = datetime.now(tz) + timedelta(days=2)
    while future.weekday() != 5:
        future += timedelta(days=1)
    req = BookingRequest(booking_date=future.date(), booking_time=time(10, 0), name="Jan", email="jan@example.com")
    with pytest.raises(InvalidSlotError):
        booking_service.create_booking(channel=channel, request=req)


@pytest.mark.django_db
def test_create_booking_rejects_out_of_hours():
    enable_global_settings(bookings=True)
    channel = ChannelFactory()
    BookingConfigFactory(channel=channel)
    when = _next_weekday_at(20)  # 8pm > end_hour (17)
    req = BookingRequest(booking_date=when.date(), booking_time=time(20, 0), name="Jan", email="jan@example.com")
    with pytest.raises(InvalidSlotError):
        booking_service.create_booking(channel=channel, request=req)


@pytest.mark.django_db
def test_create_booking_rejects_past_slot():
    enable_global_settings(bookings=True)
    channel = ChannelFactory()
    BookingConfigFactory(channel=channel)
    past = (timezone.now() - timedelta(days=1)).date()
    req = BookingRequest(booking_date=past, booking_time=time(10, 0), name="Jan", email="jan@example.com")
    with pytest.raises(InvalidSlotError):
        booking_service.create_booking(channel=channel, request=req)


def _mock_backend(*, free: bool = True, event_id: str = "evt_x", meet: str = "https://meet.google.com/abc-defg-hij"):
    backend = MagicMock()
    backend.is_slot_free.return_value = free
    backend.create_event.return_value = BackendEventResult(event_id=event_id, meet_link=meet)
    return backend


@pytest.mark.django_db
def test_create_booking_happy_path_creates_contact_form_booking_lead():
    enable_global_settings(bookings=True)
    channel = ChannelFactory()
    BookingConfigFactory(channel=channel)
    when = _next_weekday_at(10)
    req = BookingRequest(
        booking_date=when.date(),
        booking_time=time(10, 0),
        name="Jan Kowalski",
        email="jan@example.com",
        phone="+48123456789",
        gclid="CjwK-test",
        utm_source="google",
        utm_campaign="spring-promo",
    )
    backend = _mock_backend()
    with patch("django_contact_forms.services.booking_service.get_calendar_backend", return_value=backend):
        result = booking_service.create_booking(channel=channel, request=req)

    assert isinstance(result.contact_form, ContactForm)
    assert isinstance(result.booking, Booking)
    assert isinstance(result.lead, Lead)
    assert result.contact_form.type == "booking"
    assert result.contact_form.email == "jan@example.com"
    assert result.booking.calendar_event_id == "evt_x"
    assert result.booking.meet_link.startswith("https://meet.google.com/")
    assert result.lead.source_type == Lead.SourceType.CALENDAR
    assert result.lead.gclid == "CjwK-test"
    assert result.lead.attribution_method == Lead.AttributionMethod.GCLID
    assert result.lead.campaign_name == "spring-promo"
    assert backend.create_event.called


@pytest.mark.django_db
def test_create_booking_409_when_backend_reports_slot_taken():
    enable_global_settings(bookings=True)
    channel = ChannelFactory()
    BookingConfigFactory(channel=channel)
    when = _next_weekday_at(10)
    req = BookingRequest(booking_date=when.date(), booking_time=time(10, 0), name="Jan", email="jan@example.com")
    backend = _mock_backend(free=False)
    with patch("django_contact_forms.services.booking_service.get_calendar_backend", return_value=backend):
        with pytest.raises(SlotUnavailableError):
            booking_service.create_booking(channel=channel, request=req)
    assert ContactForm.objects.count() == 0
    assert Booking.objects.count() == 0
    assert Lead.objects.count() == 0


@pytest.mark.django_db
def test_create_booking_with_ads_enabled_enqueues_meeting_booked():
    """Full chain: booking → lead → signal → enqueue."""
    enable_global_settings(bookings=True, google_ads=True)
    channel = ChannelFactory()
    BookingConfigFactory(channel=channel)
    from tests.factories import GoogleAdsConfigFactory

    GoogleAdsConfigFactory(channel=channel)
    when = _next_weekday_at(10)
    req = BookingRequest(
        booking_date=when.date(), booking_time=time(10, 0), name="Jan", email="jan@example.com", gclid="CjwK-x"
    )
    backend = _mock_backend()
    with patch("django_contact_forms.services.booking_service.get_calendar_backend", return_value=backend):
        booking_service.create_booking(channel=channel, request=req)

    assert OfflineConversionQueue.objects.count() == 1
    row = OfflineConversionQueue.objects.get()
    assert row.conversion_action_label == "Meeting Booked"
    assert row.gclid == "CjwK-x"
    assert row.status == OfflineConversionQueue.Status.PENDING


# ---------------------------------------------------------------------------
# _resolve_slot boundary cases — exercised directly because these would
# require crafting elaborate scenarios via the public create_booking surface.
# ---------------------------------------------------------------------------


def _future_weekday(tz: ZoneInfo) -> date:
    candidate = (datetime.now(tz) + timedelta(days=2)).date()
    while candidate.weekday() >= 5:
        candidate += timedelta(days=1)
    return candidate


@pytest.mark.django_db
def test_resolve_slot_accepts_window_start_exactly():
    """A slot starting on win.start_time and ending within the window must be accepted."""
    tz = ZoneInfo("Europe/Warsaw")
    cfg = BookingConfigFactory(
        slot_duration_minutes=45, time_windows=[{"start_time": time(10, 0), "end_time": time(12, 30)}]
    )
    booking_date = _future_weekday(tz)
    start, end = _resolve_slot(booking_date, time(10, 0), cfg, tz, list(cfg.time_windows.all()))
    assert start.time() == time(10, 0)
    assert end.time() == time(10, 45)


@pytest.mark.django_db
def test_resolve_slot_rejects_overflow_past_window_end():
    """Slot whose END exceeds win.end_time must be rejected — ``time()``-based
    code would silently roll past midnight and let it through; the datetime-aware
    implementation catches it."""
    tz = ZoneInfo("Europe/Warsaw")
    # Window ends 12:30. 12:00 + 45min = 12:45 → overflow.
    cfg = BookingConfigFactory(
        slot_duration_minutes=45, time_windows=[{"start_time": time(10, 0), "end_time": time(12, 30)}]
    )
    booking_date = _future_weekday(tz)
    with pytest.raises(InvalidSlotError, match="not within any configured time window"):
        _resolve_slot(booking_date, time(12, 0), cfg, tz, list(cfg.time_windows.all()))


@pytest.mark.django_db
def test_resolve_slot_rejects_off_grid_start():
    """Booking time inside the window but not on the slot grid must be rejected."""
    tz = ZoneInfo("Europe/Warsaw")
    cfg = BookingConfigFactory(
        slot_duration_minutes=30, time_windows=[{"start_time": time(10, 0), "end_time": time(12, 0)}]
    )
    booking_date = _future_weekday(tz)
    # 10:07 is inside [10:00, 12:00) but not on a 30-min boundary from 10:00.
    with pytest.raises(InvalidSlotError, match="not aligned"):
        _resolve_slot(booking_date, time(10, 7), cfg, tz, list(cfg.time_windows.all()))


@pytest.mark.django_db
def test_resolve_slot_rejects_nonzero_seconds():
    """Sub-minute precision is off-grid and must be rejected before alignment check."""
    tz = ZoneInfo("Europe/Warsaw")
    cfg = BookingConfigFactory(time_windows=[{"start_time": time(9, 0), "end_time": time(17, 0)}])
    booking_date = _future_weekday(tz)
    with pytest.raises(InvalidSlotError, match="zero seconds"):
        _resolve_slot(booking_date, time(10, 0, 1), cfg, tz, list(cfg.time_windows.all()))


@pytest.mark.django_db
def test_resolve_slot_rejects_nonzero_microseconds():
    tz = ZoneInfo("Europe/Warsaw")
    cfg = BookingConfigFactory(time_windows=[{"start_time": time(9, 0), "end_time": time(17, 0)}])
    booking_date = _future_weekday(tz)
    with pytest.raises(InvalidSlotError, match="zero seconds"):
        _resolve_slot(booking_date, time(10, 0, 0, 1), cfg, tz, list(cfg.time_windows.all()))


@pytest.mark.django_db
def test_resolve_slot_accepts_secondary_window():
    """Booking that lands inside the second window (not the first) must succeed."""
    tz = ZoneInfo("Europe/Warsaw")
    cfg = BookingConfigFactory(
        slot_duration_minutes=45,
        time_windows=[
            {"order": 0, "start_time": time(10, 0), "end_time": time(12, 30)},
            {"order": 1, "start_time": time(16, 0), "end_time": time(17, 0)},
        ],
    )
    booking_date = _future_weekday(tz)
    start, end = _resolve_slot(booking_date, time(16, 0), cfg, tz, list(cfg.time_windows.all()))
    assert start.time() == time(16, 0)
    assert end.time() == time(16, 45)


@pytest.mark.django_db
def test_resolve_slot_rejects_between_windows():
    """Booking time in the gap between two windows must be rejected."""
    tz = ZoneInfo("Europe/Warsaw")
    cfg = BookingConfigFactory(
        slot_duration_minutes=30,
        time_windows=[
            {"order": 0, "start_time": time(10, 0), "end_time": time(12, 30)},
            {"order": 1, "start_time": time(16, 0), "end_time": time(17, 0)},
        ],
    )
    booking_date = _future_weekday(tz)
    with pytest.raises(InvalidSlotError, match="not within any configured time window"):
        _resolve_slot(booking_date, time(14, 0), cfg, tz, list(cfg.time_windows.all()))


@pytest.mark.django_db
def test_resolve_slot_lazy_loads_windows_when_omitted():
    """When the optional ``windows`` argument is None the function falls back to
    ``config.time_windows.all()`` — exercised through the public surface to pin
    the contract."""
    tz = ZoneInfo("Europe/Warsaw")
    cfg = BookingConfigFactory(time_windows=[{"start_time": time(9, 0), "end_time": time(17, 0)}])
    booking_date = _future_weekday(tz)
    start, _ = _resolve_slot(booking_date, time(10, 0), cfg, tz)
    assert start.time() == time(10, 0)
