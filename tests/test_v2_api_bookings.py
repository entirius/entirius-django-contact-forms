# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Public v2 API: bookings (slots + create)."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest
from rest_framework.test import APIClient

from django_contact_forms.models import APIKey, Booking, ContactForm, Lead
from django_contact_forms.services.calendar.backends.base import BackendEventResult
from tests.factories import APIKeyFactory, BookingConfigFactory, ChannelFactory, enable_global_settings


def _next_weekday():
    tz = ZoneInfo("Europe/Warsaw")
    candidate = datetime.now(tz) + timedelta(days=2)
    while candidate.weekday() >= 5:
        candidate += timedelta(days=1)
    return candidate


def _setup_channel():
    enable_global_settings(bookings=True)
    channel = ChannelFactory()
    BookingConfigFactory(channel=channel)
    raw_key = "raw-booking-key-xyz"
    APIKey.objects.create(channel=channel, key=raw_key, scope=APIKey.Scope.BOOKING)
    return channel, raw_key


@pytest.mark.django_db
def test_booking_create_requires_api_key():
    channel = ChannelFactory()
    BookingConfigFactory(channel=channel)
    enable_global_settings(bookings=True)
    resp = APIClient().post(f"/api/contact-forms/v2/{channel.idx}/bookings/", {}, format="json")
    assert resp.status_code == 401


@pytest.mark.django_db
def test_booking_create_rejects_contact_form_scoped_key():
    """A contact-form key must NOT be usable for booking endpoints."""
    channel = ChannelFactory()
    BookingConfigFactory(channel=channel)
    enable_global_settings(bookings=True)
    contact_key = APIKeyFactory(channel=channel, scope=APIKey.Scope.CONTACT_FORM)
    client = APIClient()
    client.credentials(HTTP_X_API_KEY=contact_key.key)
    resp = client.post(f"/api/contact-forms/v2/{channel.idx}/bookings/", {}, format="json")
    assert resp.status_code == 401


@pytest.mark.django_db
def test_booking_create_400_when_disabled_globally():
    enable_global_settings(bookings=False)
    channel = ChannelFactory()
    BookingConfigFactory(channel=channel)
    APIKey.objects.create(channel=channel, key="k", scope=APIKey.Scope.BOOKING)
    client = APIClient()
    client.credentials(HTTP_X_API_KEY="k")
    when = _next_weekday()
    resp = client.post(
        f"/api/contact-forms/v2/{channel.idx}/bookings/",
        {"booking_date": when.date().isoformat(), "booking_time": "10:00", "name": "Jan", "email": "jan@example.com"},
        format="json",
    )
    assert resp.status_code == 400


@pytest.mark.django_db
def test_booking_create_happy_path():
    channel, key = _setup_channel()
    client = APIClient()
    client.credentials(HTTP_X_API_KEY=key)
    when = _next_weekday()

    backend = MagicMock()
    backend.is_slot_free.return_value = True
    backend.create_event.return_value = BackendEventResult(event_id="evt_z", meet_link="https://meet/abc")

    # django-email's EmailService subclasses query django_email_channel in
    # __init__; that table isn't in tests/settings.py's INSTALLED_APPS, so
    # stub the two classes out — their behaviour is tested separately.
    with (
        patch("django_contact_forms.services.booking_service.get_calendar_backend", return_value=backend),
        patch("django_email.service.contact_forms.booking_confirmation.BookingConfirmationEmail"),
        patch("django_email.service.contact_forms.booking_admin_notification.BookingAdminNotificationEmail"),
    ):
        resp = client.post(
            f"/api/contact-forms/v2/{channel.idx}/bookings/",
            {
                "booking_date": when.date().isoformat(),
                "booking_time": "10:00",
                "name": "Jan Kowalski",
                "email": "jan@example.com",
                "gclid": "CjwK-test",
            },
            format="json",
        )

    assert resp.status_code == 201, resp.json()
    body = resp.json()
    assert body["event_id"] == "evt_z"
    assert body["meet_link"] == "https://meet/abc"
    assert body["lead_id"] > 0
    assert body["contact_form_id"]
    assert ContactForm.objects.count() == 1
    assert Booking.objects.count() == 1
    assert Lead.objects.count() == 1


@pytest.mark.django_db
def test_booking_create_409_on_slot_collision():
    channel, key = _setup_channel()
    client = APIClient()
    client.credentials(HTTP_X_API_KEY=key)
    when = _next_weekday()

    backend = MagicMock()
    backend.is_slot_free.return_value = False  # taken between validation and persist

    with patch("django_contact_forms.services.booking_service.get_calendar_backend", return_value=backend):
        resp = client.post(
            f"/api/contact-forms/v2/{channel.idx}/bookings/",
            {
                "booking_date": when.date().isoformat(),
                "booking_time": "10:00",
                "name": "Jan",
                "email": "jan@example.com",
            },
            format="json",
        )

    assert resp.status_code == 409
    assert ContactForm.objects.count() == 0


@pytest.mark.django_db
def test_booking_slots_returns_grid():
    channel, key = _setup_channel()
    client = APIClient()
    client.credentials(HTTP_X_API_KEY=key)

    backend = MagicMock()
    backend.is_slot_free.return_value = True
    backend.get_busy_periods.return_value = []

    with patch("django_contact_forms.services.booking_service.get_calendar_backend", return_value=backend):
        resp = client.get(f"/api/contact-forms/v2/{channel.idx}/bookings/slots/?days=2")

    assert resp.status_code == 200
    body = resp.json()
    assert body["timezone"] == "Europe/Warsaw"
    assert body["slot_duration_minutes"] == 30
    assert isinstance(body["days"], list)
    if body["days"]:  # if any weekdays in the next 2 days
        assert "slots" in body["days"][0]
    # One wide freebusy call per request, not one per day in the horizon.
    assert backend.get_busy_periods.call_count == 1


@pytest.mark.django_db
def test_booking_create_validation_400():
    channel, key = _setup_channel()
    client = APIClient()
    client.credentials(HTTP_X_API_KEY=key)
    resp = client.post(
        f"/api/contact-forms/v2/{channel.idx}/bookings/",
        {"booking_date": "not-a-date", "booking_time": "10:00", "name": "x", "email": "y"},
        format="json",
    )
    assert resp.status_code == 400


# --- Booking email notifications --------------------------------------------


def _post_booking(client, channel_idx, when):
    return client.post(
        f"/api/contact-forms/v2/{channel_idx}/bookings/",
        {
            "booking_date": when.date().isoformat(),
            "booking_time": "10:00",
            "name": "Jan Kowalski",
            "email": "jan@example.com",
        },
        format="json",
    )


@pytest.mark.django_db
def test_booking_dispatches_booker_confirmation():
    """Both EmailService subclasses are instantiated — one for the booker, one
    for the admin (CONTACT_FORM_SEND_ADMIN_EMAIL defaults to True, so the
    global-fallback branch opens the admin dispatch)."""
    channel, key = _setup_channel()
    client = APIClient()
    client.credentials(HTTP_X_API_KEY=key)
    when = _next_weekday()

    backend = MagicMock()
    backend.is_slot_free.return_value = True
    backend.create_event.return_value = BackendEventResult(event_id="evt", meet_link="https://meet/x")

    confirm_mock = MagicMock()
    admin_mock = MagicMock()
    with (
        patch("django_contact_forms.services.booking_service.get_calendar_backend", return_value=backend),
        patch(
            "django_email.service.contact_forms.booking_confirmation.BookingConfirmationEmail",
            return_value=confirm_mock,
        ) as confirm_cls,
        patch(
            "django_email.service.contact_forms.booking_admin_notification.BookingAdminNotificationEmail",
            return_value=admin_mock,
        ) as admin_cls,
    ):
        resp = _post_booking(client, channel.idx, when)

    assert resp.status_code == 201, resp.json()
    confirm_cls.assert_called_once()
    admin_cls.assert_called_once()
    # Booker sees their own email address on the send call.
    confirm_mock.send.assert_called_once()
    assert confirm_mock.send.call_args.kwargs["email"] == ["jan@example.com"]
    # Admin notification goes to channel.admin_email (no FormNotificationConfig override).
    admin_mock.send.assert_called_once()
    assert admin_mock.send.call_args.kwargs["email"] == [channel.admin_email]


@pytest.mark.django_db
def test_booking_admin_dispatch_opt_in_via_form_notification_config():
    """FormNotificationConfig with recipient_email routes the admin email to the override."""
    from tests.factories import FormNotificationConfigFactory

    channel, key = _setup_channel()
    FormNotificationConfigFactory(
        channel=channel,
        form_type="booking",
        slug="",
        send_email=True,
        recipient_email="sales-desk@example.com",
    )

    client = APIClient()
    client.credentials(HTTP_X_API_KEY=key)
    when = _next_weekday()

    backend = MagicMock()
    backend.is_slot_free.return_value = True
    backend.create_event.return_value = BackendEventResult(event_id="evt", meet_link="")

    confirm_mock = MagicMock()
    admin_mock = MagicMock()
    with (
        patch("django_contact_forms.services.booking_service.get_calendar_backend", return_value=backend),
        patch(
            "django_email.service.contact_forms.booking_confirmation.BookingConfirmationEmail",
            return_value=confirm_mock,
        ),
        patch(
            "django_email.service.contact_forms.booking_admin_notification.BookingAdminNotificationEmail",
            return_value=admin_mock,
        ),
    ):
        resp = _post_booking(client, channel.idx, when)

    assert resp.status_code == 201
    confirm_mock.send.assert_called_once()
    assert confirm_mock.send.call_args.kwargs["email"] == ["jan@example.com"]
    admin_mock.send.assert_called_once()
    assert admin_mock.send.call_args.kwargs["email"] == ["sales-desk@example.com"]


@pytest.mark.django_db
def test_booking_admin_dispatch_suppressed_when_form_notification_config_off():
    """Exact-match row with send_email=False blocks admin notification; booker still sent."""
    from tests.factories import FormNotificationConfigFactory

    channel, key = _setup_channel()
    FormNotificationConfigFactory(channel=channel, form_type="booking", slug="", send_email=False)

    client = APIClient()
    client.credentials(HTTP_X_API_KEY=key)
    when = _next_weekday()

    backend = MagicMock()
    backend.is_slot_free.return_value = True
    backend.create_event.return_value = BackendEventResult(event_id="evt", meet_link="")

    confirm_mock = MagicMock()
    admin_mock = MagicMock()
    with (
        patch("django_contact_forms.services.booking_service.get_calendar_backend", return_value=backend),
        patch(
            "django_email.service.contact_forms.booking_confirmation.BookingConfirmationEmail",
            return_value=confirm_mock,
        ),
        patch(
            "django_email.service.contact_forms.booking_admin_notification.BookingAdminNotificationEmail",
            return_value=admin_mock,
        ),
    ):
        resp = _post_booking(client, channel.idx, when)

    assert resp.status_code == 201
    confirm_mock.send.assert_called_once()
    admin_mock.send.assert_not_called()


@pytest.mark.django_db
def test_failed_booking_does_not_dispatch_any_email():
    """When the backend says slot unavailable, no ContactForm is created and no
    notification goes out — booker shouldn't get a bogus 'confirmed' email."""
    channel, key = _setup_channel()
    client = APIClient()
    client.credentials(HTTP_X_API_KEY=key)
    when = _next_weekday()

    backend = MagicMock()
    backend.is_slot_free.return_value = False

    confirm_mock = MagicMock()
    admin_mock = MagicMock()
    with (
        patch("django_contact_forms.services.booking_service.get_calendar_backend", return_value=backend),
        patch(
            "django_email.service.contact_forms.booking_confirmation.BookingConfirmationEmail",
            return_value=confirm_mock,
        ),
        patch(
            "django_email.service.contact_forms.booking_admin_notification.BookingAdminNotificationEmail",
            return_value=admin_mock,
        ),
    ):
        resp = _post_booking(client, channel.idx, when)

    assert resp.status_code == 409
    confirm_mock.send.assert_not_called()
    admin_mock.send.assert_not_called()
