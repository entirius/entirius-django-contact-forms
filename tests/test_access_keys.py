# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""The access path: with django_access installed every widget key is an access token (``verify_api_key``).

Legacy keys reach it only through the import (``make_api_key``); the legacy table is never read on this path.
"""

import secrets
from datetime import timedelta
from unittest.mock import patch

import pytest

pytest.importorskip("django_access")

from django.contrib import admin  # noqa: E402
from django.core.cache import cache  # noqa: E402
from django.core.management import CommandError, call_command  # noqa: E402
from django.utils import timezone  # noqa: E402
from django_access.models import ApiToken, Application  # noqa: E402
from django_access.services.access_service import Actor  # noqa: E402
from django_access.services.tokens import hash_key, issue_token, revoke_token  # noqa: E402
from rest_framework.test import APIClient  # noqa: E402
from rest_framework.throttling import SimpleRateThrottle  # noqa: E402

from django_contact_forms.api.public.throttling import key_fingerprint  # noqa: E402
from django_contact_forms.models import APIKey  # noqa: E402
from tests.conftest import BOOKING_SCOPE, SUBMIT_SCOPE  # noqa: E402
from tests.factories import BookingConfigFactory, ChannelFactory, enable_global_settings  # noqa: E402

CHANNEL, OTHER = "key-channel", "other-channel"
FOREIGN_SCOPE = "agreements.subscribe"  # publishable, another module's
SYSTEM = Actor()
SLOTS_TARGET = "django_contact_forms.api.public.booking_views.booking_service.get_available_slots"


@pytest.fixture(autouse=True)
def _clean_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def channel(db):
    enable_global_settings(bookings=True)
    channel = ChannelFactory(idx=CHANNEL)
    BookingConfigFactory(channel=channel)
    return channel


@pytest.fixture
def other_channel(db):
    return ChannelFactory(idx=OTHER)


@pytest.fixture(autouse=True)
def _no_admin_email(monkeypatch):
    monkeypatch.setattr("django_contact_forms.settings.CONTACT_FORM_SEND_ADMIN_EMAIL", False)


@pytest.fixture
def issue(db):
    application = Application.objects.create(name="contact-forms-tests")

    def issue(scope: str = SUBMIT_SCOPE, channel_idx: str | None = CHANNEL) -> tuple[ApiToken, str]:
        return issue_token(application, scopes=[scope], channel_idx=channel_idx, expires_at=None, actor=SYSTEM)

    return issue


def _client(key: str, address: str = "10.0.0.1") -> APIClient:
    client = APIClient(REMOTE_ADDR=address)
    client.credentials(HTTP_X_API_KEY=key)
    return client


def _v1(key: str, idx: str = CHANNEL, address: str = "10.0.0.1"):
    return _client(key, address).post(f"/api/contact/1/{idx}/contact_form/", {"email": "visitor@example.com"})


def _submit(key: str, idx: str = CHANNEL, address: str = "10.0.0.1"):
    body = {"email": "visitor@example.com"}
    return _client(key, address).post(f"/api/contact-forms/v2/{idx}/submit/", body, format="json")


def _form_types(key: str, idx: str = CHANNEL, address: str = "10.0.0.1"):
    return _client(key, address).get(f"/api/contact-forms/v2/{idx}/form-types/")


def _slots(key: str, idx: str = CHANNEL, address: str = "10.0.0.1"):
    with patch(SLOTS_TARGET, return_value=[]):
        return _client(key, address).get(f"/api/contact-forms/v2/{idx}/bookings/slots/")


ROUTES = {"v1": (_v1, SUBMIT_SCOPE), "submit": (_submit, SUBMIT_SCOPE), "slots": (_slots, BOOKING_SCOPE)}
OK = {"v1": 200, "submit": 201, "slots": 200}


@pytest.mark.django_db
class TestScopes:
    def test_booking_token_submits_v1_but_not_v2_forms(self, channel, issue):
        _, raw = issue(BOOKING_SCOPE)
        assert _v1(raw).status_code == 200
        assert _submit(raw).status_code == 401
        assert _form_types(raw).status_code == 401

    def test_submit_token_cannot_book(self, channel, issue):
        _, raw = issue(SUBMIT_SCOPE)
        assert _submit(raw).status_code == 201
        assert _slots(raw).status_code == 401

    def test_v2_auth_keeps_the_channel_as_request_auth(self, channel, other_channel, issue):
        _, raw = issue(SUBMIT_SCOPE, channel_idx=None)
        response = _submit(raw, idx=OTHER)
        assert response.status_code == 201
        assert response.json()["channel_idx"] == OTHER

    def test_admin_key_header_never_stands_in(self, channel, issue):
        _, raw = issue(SUBMIT_SCOPE)
        client = APIClient()
        client.credentials(HTTP_X_API_ADMIN_KEY=raw)
        assert client.get(f"/api/contact-forms/v2/{CHANNEL}/form-types/").status_code == 401


@pytest.mark.django_db
@pytest.mark.parametrize("route", list(ROUTES))
class TestTokenLifecycle:
    def test_pinned_token_on_another_channel_is_refused(self, route, channel, other_channel, issue):
        call, scope = ROUTES[route]
        _, raw = issue(scope, channel_idx=OTHER)
        assert call(raw).status_code == 401

    def test_revoked_token_is_refused(self, route, channel, issue):
        call, scope = ROUTES[route]
        token, raw = issue(scope)
        assert call(raw).status_code == OK[route]
        revoke_token(token, actor=SYSTEM)
        assert call(raw).status_code == 401

    def test_key_only_in_the_legacy_table_is_refused(self, route, channel):
        call, scope = ROUTES[route]
        raw = secrets.token_hex(32)
        legacy_scope = APIKey.Scope.BOOKING if scope == BOOKING_SCOPE else APIKey.Scope.CONTACT_FORM
        APIKey.objects.create(channel=channel, key=raw, scope=legacy_scope)
        assert call(raw).status_code == 401

    def test_imported_legacy_key_without_expiry_works(self, route, channel, make_api_key):
        call, scope = ROUTES[route]
        raw = make_api_key(channel=channel, scope=scope)
        assert ApiToken.objects.get(key_hash=hash_key(raw)).expires_at is None
        assert call(raw).status_code == OK[route]


def _wrong_scope(route: str) -> str:
    return {"v1": FOREIGN_SCOPE, "submit": BOOKING_SCOPE, "slots": SUBMIT_SCOPE}[route]


def _failing_keys(issue, route: str) -> dict[str, str]:
    """The five ways a key fails, each a real token except ``unknown``."""
    scope = ROUTES[route][1]
    expired, expired_raw = issue(scope)
    ApiToken.objects.filter(pk=expired.pk).update(expires_at=timezone.now() - timedelta(minutes=1))
    revoked, revoked_raw = issue(scope)
    revoke_token(revoked, actor=SYSTEM)
    return {
        "unknown": "ent_api_" + secrets.token_urlsafe(32),
        "expired": expired_raw,
        "revoked": revoked_raw,
        "wrong scope": issue(_wrong_scope(route))[1],
        "wrong channel": issue(scope, channel_idx=OTHER)[1],
    }


@pytest.mark.django_db
@pytest.mark.parametrize("route", list(ROUTES))
def test_every_failure_gives_one_response(route, channel, other_channel, issue):
    call = ROUTES[route][0]
    outcomes = {kind: call(raw) for kind, raw in _failing_keys(issue, route).items()}
    answers = {kind: (response.status_code, response.content) for kind, response in outcomes.items()}
    assert len(set(answers.values())) == 1, answers
    assert answers["unknown"][0] == 401


# --- Throttles ---


def _rates(**rates: str):
    """Override ``DEFAULT_THROTTLE_RATES`` the way a service does (rates resolve when a throttle is built)."""
    return patch.object(SimpleRateThrottle, "THROTTLE_RATES", rates)


def _cache_keys() -> list[str]:
    return list(cache._cache.keys())  # locmem: the stored names, prefix and version included


@pytest.mark.django_db
@pytest.mark.parametrize("route", ["submit", "slots"])
def test_throttle_cache_keys_hold_no_key_material(route, channel, issue):
    call, scope = ROUTES[route]
    token, raw = issue(scope)
    assert call(raw).status_code == OK[route]
    names = _cache_keys()
    assert names
    assert not [name for name in names if raw in name or key_fingerprint(raw) in name or token.key_hash in name]
    assert any(f"token:{token.pk}:10.0.0.1" in name for name in names)
    assert any(name.endswith(f"_token_token:{token.pk}") for name in names)


@pytest.mark.django_db
def test_legacy_path_buckets_by_a_key_fingerprint(channel):
    raw = secrets.token_hex(32)
    APIKey.objects.create(channel=channel, key=raw, scope=APIKey.Scope.CONTACT_FORM)
    with patch("django_contact_forms.utils.api_keys.access_installed", return_value=False):
        assert _form_types(raw).status_code == 200
    names = _cache_keys()
    assert not [name for name in names if raw in name]
    assert [name for name in names if name.endswith(f"contact_forms_form_types_{key_fingerprint(raw)}")]


@pytest.mark.django_db
def test_two_addresses_with_one_token_get_separate_visitor_buckets(channel, issue):
    _, raw = issue(SUBMIT_SCOPE)
    with _rates(contact_forms_form_types="2/hour", contact_forms_form_types_token="100/hour"):
        assert [_form_types(raw, address="10.0.0.1").status_code for _ in range(3)] == [200, 200, 429]
        assert _form_types(raw, address="10.0.0.2").status_code == 200


@pytest.mark.django_db
def test_per_token_ceiling_throttles_across_addresses(channel, issue):
    _, raw = issue(SUBMIT_SCOPE)
    with _rates(contact_forms_form_types="2/hour", contact_forms_form_types_token="3/hour"):
        assert [_form_types(raw, address="10.0.0.1").status_code for _ in range(2)] == [200, 200]
        assert _form_types(raw, address="10.0.0.2").status_code == 200
        assert _form_types(raw, address="10.0.0.3").status_code == 429
    _, another = issue(SUBMIT_SCOPE)
    assert _form_types(another, address="10.0.0.3").status_code == 200


@pytest.mark.django_db
def test_requests_refused_per_visitor_do_not_spend_the_ceiling(channel, issue):
    _, raw = issue(SUBMIT_SCOPE)
    with _rates(contact_forms_form_types="1/hour", contact_forms_form_types_token="3/hour"):
        assert [_form_types(raw, address="10.0.0.1").status_code for _ in range(5)] == [200, 429, 429, 429, 429]
        assert _form_types(raw, address="10.0.0.2").status_code == 200
        assert _form_types(raw, address="10.0.0.3").status_code == 200


@pytest.mark.parametrize(
    ("rates", "expected"),
    [({}, ("10/hour", "200/hour")), ({"contact_forms_booking": "5/minute"}, ("5/minute", "100/minute"))],
)
def test_unconfigured_ceiling_is_twenty_times_the_visitor_rate(rates, expected):
    from django_contact_forms.api.public.throttling import BookingThrottle

    with _rates(**rates):
        visitor = BookingThrottle()
        assert (visitor.rate, BookingThrottle.ceiling(visitor.rate).rate) == expected


# --- Command and admin ---


@pytest.mark.django_db
def test_generate_command_refuses_and_names_the_token_command():
    with pytest.raises(CommandError, match=f"access_token create --scope {SUBMIT_SCOPE}"):
        call_command("forms-generate-api-key")
    assert not APIKey.objects.exists()


@pytest.mark.django_db
@pytest.mark.parametrize("access", [True, False])
def test_admin_pages_never_show_the_raw_key(access, channel, admin_user, rf, settings):
    settings.ROOT_URLCONF = "tests.admin_urls"  # the module URLconf has no admin
    key = APIKey.objects.create(channel=channel)
    model_admin = admin.site.get_model_admin(APIKey)
    request = rf.get("/")
    request.user = admin_user
    with patch("django_contact_forms.admin.api_key.access_installed", return_value=access):
        assert model_admin.has_add_permission(request) is not access
        assert model_admin.has_change_permission(request, key) is not access
        assert model_admin.has_delete_permission(request, key) is not access
        pages = (model_admin.changelist_view(request), model_admin.change_view(request, str(key.pk)))
        for response in pages:
            html = response.render().content.decode()
            assert response.status_code == 200
            assert key.key not in html
            assert f"…{key.key[-4:]}" in html
