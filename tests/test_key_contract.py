# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Characterization of today's contact-forms key contract (X-API-KEY, scopes ``contact_form`` / ``booking``).

Pins what the keyed routes answer — quirks included — so moving the key checks onto another key store cannot
change a status, a body or the ``request.auth`` side contract (the views read the channel from it). Keys come
only from the ``make_api_key`` helper.

The module has no key-free public route: every public v1/v2 route is keyed, the admin API is JWT-only.
"""

import secrets
from unittest.mock import patch

import pytest
from rest_framework.test import APIClient

from tests.conftest import BOOKING_SCOPE
from tests.factories import BookingConfigFactory, ChannelFactory, FormTypeFactory, enable_global_settings

SUBMIT_BODY = {"email": "visitor@example.com"}


@pytest.fixture(autouse=True)
def _clear_throttle_cache():
    """The submit throttle buckets by key value; counters are process-wide."""
    from django.core.cache import cache

    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def channel(db):
    return ChannelFactory(idx="key-channel")


@pytest.fixture
def other_channel(db):
    return ChannelFactory(idx="other-channel")


@pytest.fixture(autouse=True)
def _live_keys(channel, make_api_key):
    """Valid keys exist in every test, so a refusal proves the lookup, not an empty key store."""
    make_api_key(channel=channel)
    make_api_key(channel=channel, scope=BOOKING_SCOPE)


def _client(key: str | None) -> APIClient:
    client = APIClient()
    if key is not None:
        client.credentials(HTTP_X_API_KEY=key)
    return client


# --- v1 contact_form (@channel_view): 401, and any scope submits (quirk) ---


@pytest.fixture
def _no_admin_email(monkeypatch):
    monkeypatch.setattr("django_contact_forms.settings.CONTACT_FORM_SEND_ADMIN_EMAIL", False)


def _v1_submit(key: str | None, channel_idx: str = "key-channel"):
    return _client(key).post(f"/api/contact/1/{channel_idx}/contact_form/", SUBMIT_BODY)


def _v1_refusal(response) -> tuple[int, str, str]:
    """The v1 envelope puts the refusal text in ``data``, not in ``meta.message`` (quirk: positional arg)."""
    body = response.json()
    return response.status_code, body["meta"]["status"], body["data"]


@pytest.mark.django_db
@pytest.mark.usefixtures("_no_admin_email")
class TestV1ChannelView:
    def test_missing_key_is_401(self, channel):
        assert _v1_refusal(_v1_submit(None)) == (401, "UNAUTHORIZED", "Invalid api key")

    def test_wrong_key_is_401(self, channel):
        assert _v1_refusal(_v1_submit(secrets.token_hex(32))) == (401, "UNAUTHORIZED", "Invalid api key")

    def test_other_channel_key_is_refused_like_a_wrong_key(self, channel, other_channel, make_api_key):
        wrong = _v1_submit(secrets.token_hex(32))
        foreign_key = make_api_key(channel=other_channel)
        foreign = _v1_submit(foreign_key)
        assert _v1_refusal(foreign) == _v1_refusal(wrong)
        assert foreign_key not in foreign.content.decode()

    def test_unknown_channel_is_404_before_the_key(self, channel, make_api_key):
        assert _v1_submit(make_api_key(channel=channel), channel_idx="no-such-channel").status_code == 404

    def test_contact_form_key_submits(self, channel, make_api_key):
        response = _v1_submit(make_api_key(channel=channel))
        assert response.status_code == 200
        assert response.json()["data"]["email"] == SUBMIT_BODY["email"]

    def test_booking_key_also_submits(self, channel, make_api_key):
        assert _v1_submit(make_api_key(channel=channel, scope=BOOKING_SCOPE)).status_code == 200


# --- v2 submit / form-types (APIKeyAuthentication, scope contact_form) ---


def _v2_submit(key: str | None, channel_idx: str = "key-channel"):
    return _client(key).post(f"/api/contact-forms/v2/{channel_idx}/submit/", SUBMIT_BODY, format="json")


@pytest.mark.django_db
class TestV2Submit:
    def test_missing_key_is_401(self, channel):
        response = _v2_submit(None)
        assert response.status_code == 401
        assert response["WWW-Authenticate"] == "X-API-KEY"

    def test_wrong_key_is_401(self, channel):
        assert _v2_submit(secrets.token_hex(32)).status_code == 401

    def test_other_channel_key_is_refused_like_a_wrong_key(self, channel, other_channel, make_api_key):
        wrong = _v2_submit(secrets.token_hex(32))
        foreign_key = make_api_key(channel=other_channel)
        foreign = _v2_submit(foreign_key)
        assert foreign.status_code == wrong.status_code == 401
        assert foreign.json() == wrong.json()
        assert foreign_key not in foreign.content.decode()

    def test_booking_key_is_refused_like_a_wrong_key(self, channel, make_api_key):
        wrong = _v2_submit(secrets.token_hex(32))
        booking_key = make_api_key(channel=channel, scope=BOOKING_SCOPE)
        booking = _v2_submit(booking_key)
        assert booking.status_code == wrong.status_code == 401
        assert booking.json() == wrong.json()
        assert booking_key not in booking.content.decode()

    def test_unknown_channel_is_401(self, channel, make_api_key):
        assert _v2_submit(make_api_key(channel=channel), channel_idx="no-such-channel").status_code == 401

    def test_right_key_submits_on_the_key_channel(self, channel, make_api_key):
        response = _v2_submit(make_api_key(channel=channel))
        assert response.status_code == 201
        assert response.json()["channel_idx"] == channel.idx


@pytest.mark.django_db
def test_form_types_without_a_key_is_401(channel):
    assert _client(None).get(f"/api/contact-forms/v2/{channel.idx}/form-types/").status_code == 401


@pytest.mark.django_db
def test_form_types_list_only_the_key_channel(channel, other_channel, make_api_key):
    FormTypeFactory(channel=channel, code="mine")
    FormTypeFactory(channel=other_channel, code="theirs")
    response = _client(make_api_key(channel=channel)).get(f"/api/contact-forms/v2/{channel.idx}/form-types/")
    assert response.status_code == 200
    assert [form_type["code"] for form_type in response.json()["results"]] == ["mine"]


# --- v2 bookings (BookingAPIKeyAuthentication, scope booking) ---


@pytest.fixture
def booking_channel(channel):
    enable_global_settings(bookings=True)
    BookingConfigFactory(channel=channel)
    return channel


SLOTS_TARGET = "django_contact_forms.api.public.booking_views.booking_service.get_available_slots"


def _slots(key: str | None):
    with patch(SLOTS_TARGET, return_value=[]):
        return _client(key).get("/api/contact-forms/v2/key-channel/bookings/slots/")


@pytest.mark.django_db
class TestV2Bookings:
    def test_missing_key_is_401(self, booking_channel):
        assert _slots(None).status_code == 401

    def test_contact_form_key_is_refused_like_a_wrong_key(self, booking_channel, make_api_key):
        wrong = _slots(secrets.token_hex(32))
        form_key = make_api_key(channel=booking_channel)
        refused = _slots(form_key)
        assert refused.status_code == wrong.status_code == 401
        assert refused.json() == wrong.json()
        assert form_key not in refused.content.decode()

    def test_other_channel_booking_key_is_401(self, booking_channel, other_channel, make_api_key):
        assert _slots(make_api_key(channel=other_channel, scope=BOOKING_SCOPE)).status_code == 401

    def test_booking_key_lists_slots_of_the_key_channel(self, booking_channel, make_api_key):
        key = make_api_key(channel=booking_channel, scope=BOOKING_SCOPE)
        with patch(SLOTS_TARGET, return_value=[]) as get_slots:
            response = _client(key).get(f"/api/contact-forms/v2/{booking_channel.idx}/bookings/slots/")
        assert response.status_code == 200
        assert response.json()["days"] == []
        assert get_slots.call_args.kwargs["channel"] == booking_channel
