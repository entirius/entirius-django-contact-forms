# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""No exception text reaches a v2 response (CodeQL py/stack-trace-exposure).

An exception from a lower layer answers the generic 500 of the v2 handler: an error id, never its message. A
refusal the module wrote for the client (``ClientError``) keeps its message; ``BookingDisabledError`` names internal
settings, so the public API answers with its own sentence.
"""

from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from django_contact_forms.models import APIKey
from django_contact_forms.services.exceptions import BookingDisabledError, InvalidSlotError, SlotUnavailableError
from tests.conftest import import_keys_into_access
from tests.factories import BookingConfigFactory, ChannelFactory, enable_global_settings

# What a driver or SDK error carries: a path, a host, a token. None of it may reach a client.
LEAK = "OperationalError: /srv/app/.env token=sk-leak-4f2a host=db-internal"

ADMIN = "/api/contact-forms/v2/admin"
SERVICES = "django_contact_forms.services"

ADMIN_LISTS = [
    (f"{ADMIN}/submissions/", f"{SERVICES}.contact_form_service.list_submissions"),
    (f"{ADMIN}/leads/", f"{SERVICES}.lead_service.list_leads"),
    (f"{ADMIN}/offline-conversions/", f"{SERVICES}.conversions.queue_service.list_conversions"),
    (f"{ADMIN}/bookings/", f"{SERVICES}.booking_admin_service.list_bookings"),
]


@pytest.fixture(autouse=True)
def _v2_handler(settings):
    """The service's handler on v2 paths; DRF's default would re-raise the unhandled exception into the test."""
    settings.REST_FRAMEWORK = {
        **settings.REST_FRAMEWORK,
        "EXCEPTION_HANDLER": "django_utils.api.v2_errors.v2_exception_handler",
    }
    cache.clear()  # booking throttle buckets
    yield
    cache.clear()


@pytest.fixture
def admin_client(db):
    user = get_user_model().objects.create_superuser(username="admin", password="x", email="a@x.com")
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")
    return client


@pytest.fixture
def booking_client(db):
    enable_global_settings(bookings=True)
    channel = ChannelFactory()
    BookingConfigFactory(channel=channel)
    APIKey.objects.create(channel=channel, key="exposure-booking-key", scope=APIKey.Scope.BOOKING)
    import_keys_into_access()
    client = APIClient()
    client.credentials(HTTP_X_API_KEY="exposure-booking-key")
    return client, channel.idx


def _assert_generic_500(resp) -> None:
    assert resp.status_code == 500
    body = resp.json()
    assert body["error"] == "INTERNAL_ERROR"
    assert body["message"] == "An internal error occurred."
    assert body["debug_id"]
    assert body["details"] == []
    assert b"sk-leak" not in resp.content
    assert b"/srv/app" not in resp.content


def _booking_payload() -> dict:
    when = datetime.now(ZoneInfo("Europe/Warsaw")) + timedelta(days=2)
    return {"booking_date": when.date().isoformat(), "booking_time": "10:00", "name": "Jan", "email": "j@example.com"}


# --- Admin API ---------------------------------------------------------------


@pytest.mark.parametrize("exc_type", [ValueError, RuntimeError])
@pytest.mark.parametrize(("url", "target"), ADMIN_LISTS)
def test_admin_list_hides_a_lower_layer_exception(admin_client, url, target, exc_type):
    """A ValueError from below the service used to come back as a 400 with its text."""
    with patch(target, side_effect=exc_type(LEAK)):
        resp = admin_client.get(url)
    _assert_generic_500(resp)


def test_submission_status_update_hides_a_lower_layer_exception(admin_client):
    with patch(f"{SERVICES}.contact_form_service.update_status", side_effect=ValueError(LEAK)):
        resp = admin_client.patch(f"{ADMIN}/submissions/123456789012/", {"status": "done"}, format="json")
    _assert_generic_500(resp)


@pytest.mark.parametrize(
    ("query", "message"),
    [
        ("submissions/?ordering=bogus", "Invalid ordering: bogus"),
        ("leads/?status=bogus", "Unknown status: 'bogus'"),
        ("leads/?source_type=bogus", "Unknown source_type: 'bogus'"),
        ("offline-conversions/?status=bogus", "Unknown status: 'bogus'"),
        ("bookings/?lead_status=bogus", "Unknown lead_status: 'bogus'"),
        ("bookings/?date_from=not-a-date", "Invalid datetime: 'not-a-date'"),
    ],
)
def test_admin_list_keeps_the_filter_message_it_wrote(admin_client, query, message):
    resp = admin_client.get(f"{ADMIN}/{query}")
    assert resp.status_code == 400
    body = resp.json()
    assert body["error"] == "VALIDATION_ERROR"
    assert body["details"][0]["location"] == "query"
    assert body["details"][0]["description"].startswith(message)


def test_admin_bookings_impossible_date_answers_its_own_message(admin_client):
    """parse_datetime raises Python's "month must be in 1..12" on a well-formed impossible date."""
    resp = admin_client.get(f"{ADMIN}/bookings/?date_from=2026-13-01T10:00")
    assert resp.status_code == 400
    assert resp.json()["details"][0]["description"] == "Invalid datetime: '2026-13-01T10:00'"
    assert b"month must be" not in resp.content


# --- Public booking API ------------------------------------------------------


def test_slots_hide_a_lower_layer_exception(booking_client):
    client, idx = booking_client
    with patch(f"{SERVICES}.booking_service.get_available_slots", side_effect=RuntimeError(LEAK)):
        resp = client.get(f"/api/contact-forms/v2/{idx}/bookings/slots/")
    _assert_generic_500(resp)


def test_slots_with_bookings_off_do_not_name_internal_settings(booking_client):
    client, idx = booking_client
    enable_global_settings(bookings=False)
    resp = client.get(f"/api/contact-forms/v2/{idx}/bookings/slots/")
    assert resp.status_code == 400
    assert resp.json()["details"][0]["description"] == "Bookings are not available for this channel."
    assert b"ContactFormsSettings" not in resp.content


@pytest.mark.parametrize(
    ("exc", "status", "error", "text"),
    [
        (
            BookingDisabledError("Bookings are disabled globally (ContactFormsSettings.bookings_enabled=False)"),
            400,
            "VALIDATION_ERROR",
            "Bookings are not available for this channel.",
        ),
        (InvalidSlotError("2026-11-07 is a weekend; weekdays only"), 400, "VALIDATION_ERROR", None),
        (SlotUnavailableError("Slot 2026-11-09T10:00:00+01:00 no longer available"), 409, "SLOT_UNAVAILABLE", None),
    ],
    ids=["disabled", "invalid-slot", "slot-taken"],
)
def test_create_booking_refusals(booking_client, exc, status, error, text):
    """Our refusals keep their message (``text=None``: the exception's own); the disabled one gets the static one."""
    client, idx = booking_client
    with patch(f"{SERVICES}.booking_service.create_booking", side_effect=exc):
        resp = client.post(f"/api/contact-forms/v2/{idx}/bookings/", _booking_payload(), format="json")
    assert resp.status_code == status
    body = resp.json()
    assert body["error"] == error
    shown = body["details"][0]["description"] if status == 400 else body["message"]
    assert shown == (text or str(exc))
    assert b"ContactFormsSettings" not in resp.content


def test_create_booking_hides_a_lower_layer_exception(booking_client):
    client, idx = booking_client
    with patch(f"{SERVICES}.booking_service.create_booking", side_effect=RuntimeError(LEAK)):
        resp = client.post(f"/api/contact-forms/v2/{idx}/bookings/", _booking_payload(), format="json")
    _assert_generic_500(resp)
