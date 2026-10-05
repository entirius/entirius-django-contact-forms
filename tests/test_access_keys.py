# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""The access path: with django_access installed every widget key is an access token (``verify_api_key``).

Legacy keys reach it only through the import (``make_api_key``); the legacy table is never read on this path.
"""

import os
import secrets
from datetime import timedelta
from importlib import import_module
from unittest.mock import patch

import pytest

if os.environ.get("ENTIRIUS_TEST_NO_ACCESS"):
    pytest.skip("access path only (tests/settings.py leaves django_access out)", allow_module_level=True)
pytest.importorskip("django_access")

from django.contrib import admin  # noqa: E402
from django.core.cache import cache  # noqa: E402
from django.core.management import CommandError, call_command  # noqa: E402
from django.test import Client  # noqa: E402
from django.urls import reverse  # noqa: E402
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


def _client(key: str, address: str = "10.0.0.1", extra: dict | None = None) -> APIClient:
    client = APIClient(REMOTE_ADDR=address)
    client.credentials(HTTP_X_API_KEY=key, **(extra or {}))
    return client


def _v1(key: str, idx: str = CHANNEL, address: str = "10.0.0.1", extra: dict | None = None):
    return _client(key, address, extra).post(f"/api/contact/1/{idx}/contact_form/", {"email": "visitor@example.com"})


def _submit(key: str, idx: str = CHANNEL, address: str = "10.0.0.1", extra: dict | None = None):
    body = {"email": "visitor@example.com"}
    return _client(key, address, extra).post(f"/api/contact-forms/v2/{idx}/submit/", body, format="json")


def _form_types(key: str, idx: str = CHANNEL, address: str = "10.0.0.1", extra: dict | None = None):
    return _client(key, address, extra).get(f"/api/contact-forms/v2/{idx}/form-types/")


def _slots(key: str, idx: str = CHANNEL, address: str = "10.0.0.1", extra: dict | None = None):
    with patch(SLOTS_TARGET, return_value=[]):
        return _client(key, address, extra).get(f"/api/contact-forms/v2/{idx}/bookings/slots/")


def _book(key: str, idx: str = CHANNEL, address: str = "10.0.0.1", extra: dict | None = None):
    """Booking POST with an empty body: past authentication it fails validation (400), never 401."""
    return _client(key, address, extra).post(f"/api/contact-forms/v2/{idx}/bookings/", {}, format="json")


ROUTES = {
    "v1": (_v1, SUBMIT_SCOPE),
    "submit": (_submit, SUBMIT_SCOPE),
    "form_types": (_form_types, SUBMIT_SCOPE),
    "slots": (_slots, BOOKING_SCOPE),
    "book": (_book, BOOKING_SCOPE),
}
OK = {"v1": 200, "submit": 201, "form_types": 200, "slots": 200, "book": 400}


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

    @pytest.mark.parametrize("route", ["v1", "submit", "slots"])
    def test_admin_key_header_never_stands_in(self, route, channel, issue):
        """A wrong X-API-KEY must fail even when X-API-ADMIN-KEY carries a valid token."""
        call, scope = ROUTES[route]
        _, raw = issue(scope)
        assert call("ent_api_wrong", extra={"HTTP_X_API_ADMIN_KEY": raw}).status_code == 401
        assert call(raw).status_code == OK[route]


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
        APIKey.objects.create(channel=channel, key=raw, scope=_legacy_scope(scope))
        assert call(raw).status_code == 401

    def test_imported_legacy_key_without_expiry_works(self, route, channel, make_api_key):
        call, scope = ROUTES[route]
        raw = make_api_key(channel=channel, scope=scope)
        assert ApiToken.objects.get(key_hash=hash_key(raw)).expires_at is None
        assert call(raw).status_code == OK[route]


def _legacy_scope(scope: str) -> str:
    return APIKey.Scope.BOOKING if scope == BOOKING_SCOPE else APIKey.Scope.CONTACT_FORM


def _wrong_scope(route: str) -> str:
    return {
        "v1": FOREIGN_SCOPE,
        "submit": BOOKING_SCOPE,
        "form_types": BOOKING_SCOPE,
        "slots": SUBMIT_SCOPE,
        "book": SUBMIT_SCOPE,
    }[route]


def _failing_keys(issue, route: str, channel) -> dict[str, str]:
    """The six ways a key fails, each a real token except ``unknown`` and ``legacy only``."""
    scope = ROUTES[route][1]
    expired, expired_raw = issue(scope)
    ApiToken.objects.filter(pk=expired.pk).update(expires_at=timezone.now() - timedelta(minutes=1))
    revoked, revoked_raw = issue(scope)
    revoke_token(revoked, actor=SYSTEM)
    legacy_only = secrets.token_hex(32)  # in the legacy table, never imported
    APIKey.objects.create(channel=channel, key=legacy_only, scope=_legacy_scope(scope))
    return {
        "unknown": "ent_api_" + secrets.token_urlsafe(32),
        "expired": expired_raw,
        "revoked": revoked_raw,
        "wrong scope": issue(_wrong_scope(route))[1],
        "wrong channel": issue(scope, channel_idx=OTHER)[1],
        "legacy only": legacy_only,
    }


@pytest.mark.django_db
@pytest.mark.parametrize("route", list(ROUTES))
def test_every_failure_gives_one_response(route, channel, other_channel, issue):
    call = ROUTES[route][0]
    outcomes = {kind: call(raw) for kind, raw in _failing_keys(issue, route, channel).items()}
    answers = {kind: (response.status_code, response.content) for kind, response in outcomes.items()}
    assert len(set(answers.values())) == 1, answers
    assert answers["unknown"][0] == 401


# --- Throttles ---


def _rates(**rates: str):
    """Override ``DEFAULT_THROTTLE_RATES`` the way a service does (rates resolve when a throttle is built)."""
    return patch.object(SimpleRateThrottle, "THROTTLE_RATES", rates)


def _cache_keys() -> list[str]:
    return list(cache._cache.keys())  # locmem: the stored names, prefix and version included


V1_PATHS = ("contact_form/", "contact_form/question/")


@pytest.mark.django_db
@pytest.mark.parametrize("path", V1_PATHS)
@pytest.mark.parametrize("scope", [SUBMIT_SCOPE, BOOKING_SCOPE])
def test_v1_is_throttled_per_token_and_address(path, scope, channel, issue):
    _, raw = issue(scope)

    def post(address: str):
        url = f"/api/contact/1/{CHANNEL}/{path}"
        return _client(raw, address).post(url, {"email": "visitor@example.com"})

    with _rates(contact_forms_submit_v1="2/hour", contact_forms_submit_v1_token="100/hour"):
        assert [post("10.0.0.1").status_code for _ in range(2)] == [200, 200]
        refused = post("10.0.0.1")
        assert refused.status_code == 429
        assert "Retry-After" in refused.headers
        assert post("10.0.0.2").status_code == 200


@pytest.mark.django_db
def test_v1_and_v2_submit_spend_separate_buckets(channel, issue):
    _, raw = issue(SUBMIT_SCOPE)
    with _rates(contact_forms_submit="1/hour", contact_forms_submit_v1="1/hour"):
        assert [_v1(raw).status_code for _ in range(2)] == [200, 429]
        assert _submit(raw).status_code == 201


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
def test_two_addresses_with_one_token_get_separate_visitor_buckets(channel, issue):
    _, raw = issue(SUBMIT_SCOPE)
    with _rates(contact_forms_form_types="2/hour", contact_forms_form_types_token="100/hour"):
        assert [_form_types(raw, address="10.0.0.1").status_code for _ in range(3)] == [200, 200, 429]
        assert _form_types(raw, address="10.0.0.2").status_code == 200


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("route", "scope_rate"), [("submit", "contact_forms_submit"), ("slots", "contact_forms_booking")]
)
def test_per_token_ceiling_throttles_across_addresses(route, scope_rate, channel, issue):
    call, scope = ROUTES[route]
    _, raw = issue(scope)
    with _rates(**{scope_rate: "2/hour", f"{scope_rate}_token": "3/hour"}):
        assert [call(raw, address="10.0.0.1").status_code for _ in range(2)] == [OK[route]] * 2
        assert call(raw, address="10.0.0.2").status_code == OK[route]
        refused = call(raw, address="10.0.0.3")
        assert refused.status_code == 429
        assert "Retry-After" in refused.headers
    _, another = issue(scope)
    assert call(another, address="10.0.0.3").status_code == OK[route]


@pytest.mark.django_db
def test_requests_refused_per_visitor_do_not_spend_the_ceiling(channel, issue):
    _, raw = issue(SUBMIT_SCOPE)
    with _rates(contact_forms_form_types="1/hour", contact_forms_form_types_token="3/hour"):
        assert [_form_types(raw, address="10.0.0.1").status_code for _ in range(5)] == [200, 429, 429, 429, 429]
        assert _form_types(raw, address="10.0.0.2").status_code == 200
        assert _form_types(raw, address="10.0.0.3").status_code == 200


@pytest.mark.parametrize(
    ("rates", "expected"),
    [({}, ("10/hour", "200/hour")), ({"contact_forms_booking": "5/minute"}, ("5/minute", "200/hour"))],
)
def test_unconfigured_ceiling_is_twenty_times_the_class_fallback(rates, expected):
    from django_contact_forms.api.public.throttling import BookingThrottle

    with _rates(**rates):
        visitor = BookingThrottle()
        assert (visitor.rate, BookingThrottle.ceiling(visitor.fallback_rate).rate) == expected


# --- Command and admin ---


@pytest.mark.django_db
def test_generate_command_refuses_and_names_the_token_command():
    with pytest.raises(CommandError, match=f"access_token create --scope {SUBMIT_SCOPE}") as refusal:
        call_command("forms-generate-api-key")
    assert BOOKING_SCOPE in str(refusal.value)
    assert not APIKey.objects.exists()


@pytest.mark.django_db
def test_generate_command_without_access_creates_one_key_and_writes_the_file(tmp_path):
    command = import_module("django_contact_forms.management.commands.forms-generate-api-key")  # hyphenated name
    path = tmp_path / "key"
    with patch.object(command, "access_installed", return_value=False):
        call_command("forms-generate-api-key", file_path=str(path))
    key = APIKey.objects.get()
    assert path.read_text() == key.key


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


@pytest.fixture
def admin_client(admin_user, settings):
    settings.ROOT_URLCONF = "tests.admin_urls"  # the module URLconf has no admin
    client = Client()
    client.force_login(admin_user)
    return client


@pytest.mark.django_db
def test_admin_change_post_is_refused_under_access_and_leaves_the_row(channel, other_channel, admin_client):
    key = APIKey.objects.create(channel=channel)
    url = reverse("admin:django_contact_forms_apikey_change", args=[key.pk])
    with patch("django_contact_forms.admin.api_key.access_installed", return_value=True):
        response = admin_client.post(url, {"channel": other_channel.pk, "scope": APIKey.Scope.BOOKING})
    assert response.status_code == 403
    before = (key.channel_id, key.scope, key.key)
    key.refresh_from_db()
    assert (key.channel_id, key.scope, key.key) == before


@pytest.mark.django_db
def test_admin_delete_page_never_shows_the_raw_key(channel, admin_client):
    key = APIKey.objects.create(channel=channel)
    url = reverse("admin:django_contact_forms_apikey_delete", args=[key.pk])
    with patch("django_contact_forms.admin.api_key.access_installed", return_value=False):
        response = admin_client.get(url)
    assert response.status_code == 200
    assert key.key not in response.content.decode()
