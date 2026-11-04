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
from rest_framework.throttling import SimpleRateThrottle

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


@pytest.mark.django_db
@pytest.mark.usefixtures("_no_admin_email")
@pytest.mark.parametrize("path", ["contact_form/", "contact_form/question/"])
def test_v1_routes_have_their_own_submit_throttle(path, channel, make_api_key):
    """Both v1 routes create state and send mail: a widget throttle of their own (``contact_forms_submit_v1``)."""
    client = _client(make_api_key(channel=channel))
    url = f"/api/contact/1/key-channel/{path}"
    rates = {"contact_forms_submit_v1": "2/hour", "contact_forms_submit": "1/hour"}
    with patch.object(SimpleRateThrottle, "THROTTLE_RATES", rates):
        assert [client.post(url, SUBMIT_BODY).status_code for _ in range(3)] == [200, 200, 429]


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


# --- Throttle buckets: per client address under a per-key ceiling (either key path) ---


def _post_v2(key: str, **extra):
    return APIClient(**extra, HTTP_X_API_KEY=key).post(
        "/api/contact-forms/v2/key-channel/submit/", SUBMIT_BODY, format="json"
    )


def _rates(**rates: str):
    return patch.object(SimpleRateThrottle, "THROTTLE_RATES", rates)


@pytest.mark.django_db
@pytest.mark.usefixtures("_no_admin_email")
def test_two_addresses_with_one_key_have_separate_buckets(channel, make_api_key):
    key = make_api_key(channel=channel)
    with _rates(contact_forms_submit="1/hour", contact_forms_submit_token="100/hour"):
        assert _post_v2(key, REMOTE_ADDR="10.0.0.1").status_code == 201
        assert _post_v2(key, REMOTE_ADDR="10.0.0.1").status_code == 429
        assert _post_v2(key, REMOTE_ADDR="10.0.0.2").status_code == 201


@pytest.mark.django_db
@pytest.mark.usefixtures("_no_admin_email")
def test_per_key_ceiling_holds_across_addresses(channel, make_api_key):
    key = make_api_key(channel=channel)
    with _rates(contact_forms_submit="2/hour", contact_forms_submit_token="3/hour"):
        codes = [_post_v2(key, REMOTE_ADDR=f"10.0.0.{n}").status_code for n in range(1, 6)]
        assert codes == [201, 201, 201, 429, 429]
        assert _post_v2(make_api_key(channel=channel), REMOTE_ADDR="10.0.0.9").status_code == 201


@pytest.mark.django_db
@pytest.mark.usefixtures("_no_admin_email")
def test_client_ip_header_setting_names_the_visitor(channel, make_api_key, settings):
    settings.CLIENT_IP_HEADER = "HTTP_CF_CONNECTING_IP"
    key = make_api_key(channel=channel)
    with _rates(contact_forms_submit="1/hour", contact_forms_submit_token="100/hour"):
        first = _post_v2(key, REMOTE_ADDR="172.16.0.1", HTTP_CF_CONNECTING_IP="203.0.113.1")
        same = _post_v2(key, REMOTE_ADDR="172.16.0.2", HTTP_CF_CONNECTING_IP="203.0.113.1")
        other = _post_v2(key, REMOTE_ADDR="172.16.0.1", HTTP_CF_CONNECTING_IP="203.0.113.2")
        assert [first.status_code, same.status_code, other.status_code] == [201, 429, 201]


@pytest.mark.django_db
@pytest.mark.usefixtures("_no_admin_email")
@pytest.mark.parametrize("path", ["contact_form/", "contact_form/question/"])
def test_v1_buckets_per_address_under_a_key_ceiling(path, channel, make_api_key, settings):
    settings.CLIENT_IP_HEADER = "HTTP_CF_CONNECTING_IP"
    key = make_api_key(channel=channel)
    url = f"/api/contact/1/key-channel/{path}"

    def post(ip: str):
        return APIClient(HTTP_X_API_KEY=key, HTTP_CF_CONNECTING_IP=ip).post(url, SUBMIT_BODY)

    with _rates(contact_forms_submit_v1="1/hour", contact_forms_submit_v1_token="2/hour"):
        assert [post("203.0.113.1").status_code, post("203.0.113.1").status_code] == [200, 429]
        assert post("203.0.113.2").status_code == 200
        assert post("203.0.113.3").status_code == 429  # ceiling of 2 spent by two visitors


# --- Submission size limits ---


def test_submission_limit_defaults_are_tight():
    from django_contact_forms import settings as module_settings

    assert module_settings.FORMS_MAX_ATTACHMENT_COUNT == 3
    assert module_settings.FORMS_MAX_ATTACHMENT_MB_SIZE == 10
    assert module_settings.FORMS_MAX_JSON_MB_SIZE == 1


@pytest.mark.django_db
def test_default_json_limit_is_enforced():
    from django_contact_forms.utils.exceptions import JSONTooLargeException
    from tests.factories import ContactFormFactory

    with pytest.raises(JSONTooLargeException):
        ContactFormFactory(body={"message": "x" * (1024 * 1024 + 1)})


@pytest.mark.django_db
def test_default_attachment_count_limit_is_enforced():
    from django_contact_forms.utils.exceptions import AttachmentCountLimitReached
    from tests.factories import ContactFormAttachmentFactory, ContactFormFactory

    form = ContactFormFactory()
    for _ in range(3):
        ContactFormAttachmentFactory(contact_form=form)
    with pytest.raises(AttachmentCountLimitReached):
        ContactFormAttachmentFactory(contact_form=form)
