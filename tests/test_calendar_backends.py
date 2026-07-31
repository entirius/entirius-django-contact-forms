# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Calendar backend tests — LocalOnlyBackend + factory dispatch + channel lock."""

from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from django_contact_forms.models import BookingConfig
from django_contact_forms.services import booking_service
from django_contact_forms.services.booking_service import BookingRequest
from django_contact_forms.services.calendar.backends.base import BackendBusyPeriod, BackendEventResult
from django_contact_forms.services.calendar.backends.local_only import LocalOnlyBackend
from django_contact_forms.services.calendar.factory import get_calendar_backend
from django_contact_forms.services.exceptions import SlotUnavailableError
from tests.factories import (
    BookingConfigFactory,
    BookingFactory,
    ChannelFactory,
    ContactFormFactory,
    enable_global_settings,
)


def _naive(start, end):
    """Helper — produce (start, end) datetimes anchored to a stable baseline."""
    base = datetime(2030, 1, 1, 10, 0, tzinfo=UTC)
    return base + timedelta(minutes=start), base + timedelta(minutes=end)


@pytest.mark.django_db
class TestLocalOnlyBackend:
    def test_is_slot_free_empty_channel(self):
        channel = ChannelFactory()
        backend = LocalOnlyBackend(channel=channel)
        start, end = _naive(0, 30)
        assert backend.is_slot_free(start, end, "UTC") is True

    def test_is_slot_free_blocks_on_overlap_exact_match(self):
        channel = ChannelFactory()
        start, end = _naive(0, 30)
        cf = ContactFormFactory(channel=channel)
        BookingFactory(contact_form=cf, meeting_start=start, meeting_end=end)

        backend = LocalOnlyBackend(channel=channel)
        assert backend.is_slot_free(start, end, "UTC") is False

    def test_is_slot_free_blocks_on_partial_overlap_starts_inside(self):
        channel = ChannelFactory()
        existing_start, existing_end = _naive(0, 30)
        cf = ContactFormFactory(channel=channel)
        BookingFactory(contact_form=cf, meeting_start=existing_start, meeting_end=existing_end)

        backend = LocalOnlyBackend(channel=channel)
        probe_start, probe_end = _naive(15, 45)  # starts inside existing
        assert backend.is_slot_free(probe_start, probe_end, "UTC") is False

    def test_is_slot_free_blocks_on_partial_overlap_envelops(self):
        channel = ChannelFactory()
        existing_start, existing_end = _naive(10, 20)
        cf = ContactFormFactory(channel=channel)
        BookingFactory(contact_form=cf, meeting_start=existing_start, meeting_end=existing_end)

        backend = LocalOnlyBackend(channel=channel)
        probe_start, probe_end = _naive(0, 30)  # envelops existing
        assert backend.is_slot_free(probe_start, probe_end, "UTC") is False

    def test_is_slot_free_blocks_on_partial_overlap_ends_inside(self):
        """Probe starts BEFORE existing and ends INSIDE it — most realistic
        real-world collision (booker picks a time that straddles the start
        of an existing appointment)."""
        channel = ChannelFactory()
        cf = ContactFormFactory(channel=channel)
        existing_start, existing_end = _naive(15, 45)
        BookingFactory(contact_form=cf, meeting_start=existing_start, meeting_end=existing_end)

        backend = LocalOnlyBackend(channel=channel)
        probe_start, probe_end = _naive(0, 30)  # ends inside existing
        assert backend.is_slot_free(probe_start, probe_end, "UTC") is False

    def test_is_slot_free_true_for_adjacent_slot(self):
        channel = ChannelFactory()
        existing_start, existing_end = _naive(0, 30)
        cf = ContactFormFactory(channel=channel)
        BookingFactory(contact_form=cf, meeting_start=existing_start, meeting_end=existing_end)

        backend = LocalOnlyBackend(channel=channel)
        probe_start, probe_end = _naive(30, 60)  # touches but doesn't overlap
        assert backend.is_slot_free(probe_start, probe_end, "UTC") is True

    def test_is_slot_free_scopes_to_channel(self):
        """A booking on channel A must not block channel B."""
        a = ChannelFactory()
        b = ChannelFactory()
        start, end = _naive(0, 30)
        BookingFactory(contact_form=ContactFormFactory(channel=a), meeting_start=start, meeting_end=end)

        backend_b = LocalOnlyBackend(channel=b)
        assert backend_b.is_slot_free(start, end, "UTC") is True

    def test_get_busy_periods_returns_overlapping_only(self):
        channel = ChannelFactory()
        # Booking.contact_form is OneToOne — each Booking needs its own ContactForm.
        BookingFactory(
            contact_form=ContactFormFactory(channel=channel),
            meeting_start=_naive(-120, -90)[0],
            meeting_end=_naive(-120, -90)[1],
        )
        inside = BookingFactory(
            contact_form=ContactFormFactory(channel=channel),
            meeting_start=_naive(10, 20)[0],
            meeting_end=_naive(10, 20)[1],
        )
        BookingFactory(
            contact_form=ContactFormFactory(channel=channel),
            meeting_start=_naive(120, 150)[0],
            meeting_end=_naive(120, 150)[1],
        )

        backend = LocalOnlyBackend(channel=channel)
        window_start, window_end = _naive(0, 60)
        busy = backend.get_busy_periods(window_start, window_end, "UTC")
        assert len(busy) == 1
        assert busy[0].start == inside.meeting_start
        assert busy[0].end == inside.meeting_end
        assert isinstance(busy[0], BackendBusyPeriod)

    def test_create_event_returns_local_result(self):
        channel = ChannelFactory()
        backend = LocalOnlyBackend(channel=channel)
        start, end = _naive(0, 30)
        result = backend.create_event(
            start=start,
            end=end,
            summary="Demo",
            attendee_email="ada@example.com",
            description="",
            timezone="UTC",
        )
        assert isinstance(result, BackendEventResult)
        assert result.event_id.startswith("local-")
        assert result.meet_link == ""


@pytest.mark.django_db
class TestFactoryDispatch:
    def test_local_provider_returns_local_backend(self):
        channel = ChannelFactory()
        config = BookingConfigFactory(channel=channel, provider=BookingConfig.Provider.LOCAL)
        backend = get_calendar_backend(config)
        assert isinstance(backend, LocalOnlyBackend)

    def test_unknown_provider_raises(self):
        channel = ChannelFactory()
        # Start from the local-provider baseline so the test is clearly only
        # exercising the "unknown" branch — if the factory's if/elif is ever
        # reordered, this test still targets the intended fallthrough.
        config = BookingConfigFactory(channel=channel, provider=BookingConfig.Provider.LOCAL)
        # Bypass the TextChoices validator by assigning directly — simulates a
        # legacy DB row or a future value we don't know how to handle.
        config.provider = "calendly"
        with pytest.raises(ValueError) as exc_info:
            get_calendar_backend(config)
        assert "calendly" in str(exc_info.value)


@pytest.mark.django_db(transaction=True)
class TestConcurrencySerialisation:
    """The channel row lock taken at the top of create_booking serialises
    concurrent attempts. We can't test true parallelism in a single-process
    pytest run, but we can verify the sequential invariant: once a Booking
    lands, a second attempt on the same slot raises SlotUnavailableError
    through the LocalOnlyBackend path.
    """

    def test_second_booking_same_slot_raises_slot_unavailable(self):
        enable_global_settings(bookings=True)
        channel = ChannelFactory()
        # days_ahead=30 keeps our 14-day-out booking date comfortably inside
        # the horizon regardless of which weekday the test runs on.
        BookingConfigFactory(channel=channel, provider=BookingConfig.Provider.LOCAL, days_ahead=30)

        # Repeatable: always pick the next Monday at least 14 days out. The
        # absolute date still shifts per run, but the test's outcome does not.
        tz = ZoneInfo("Europe/Warsaw")
        candidate = (datetime.now(tz) + timedelta(days=14)).date()
        while candidate.weekday() != 0:  # 0 = Monday
            candidate += timedelta(days=1)

        req_kwargs = {
            "booking_date": candidate,
            "booking_time": time(10, 0),
            "name": "Ada",
            "email": "ada@example.com",
            "phone": "",
            "company": "",
            "message": "",
            "gclid": "",
            "utm_source": "",
            "utm_medium": "",
            "utm_campaign": "",
            "landing_page": "",
            "language": "en",
            "consent": True,
        }

        # First booking succeeds.
        result = booking_service.create_booking(channel=channel, request=BookingRequest(**req_kwargs))
        assert result.booking.pk

        # Second booking for the exact same slot — LocalOnlyBackend.is_slot_free
        # sees the row, booking_service raises SlotUnavailableError.
        with pytest.raises(SlotUnavailableError):
            booking_service.create_booking(channel=channel, request=BookingRequest(**req_kwargs))
