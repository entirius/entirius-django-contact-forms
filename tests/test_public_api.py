# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Tests for v2 Public API endpoints."""

from unittest.mock import patch

import pytest
from rest_framework.test import APIClient

from django_contact_forms.models import Lead
from tests.factories import (
    APIKeyFactory,
    ChannelFactory,
    FormNotificationConfigFactory,
    FormTypeFactory,
    LeadCreationRuleFactory,
)


@pytest.fixture
def channel(db):
    return ChannelFactory(idx="test-channel", label="Test Channel")


@pytest.fixture
def api_key(channel):
    return APIKeyFactory(channel=channel)


@pytest.fixture
def authed_client(api_key):
    client = APIClient()
    client.credentials(HTTP_X_API_KEY=api_key.key)
    return client


@pytest.fixture
def anon_client():
    return APIClient()


@pytest.fixture(autouse=True)
def _clear_throttle_cache():
    """Reset throttle counters between tests — the rate cache is process-wide."""
    from django.core.cache import cache

    cache.clear()
    yield
    cache.clear()


# === Auth Tests ===


@pytest.mark.django_db
class TestPublicSubmitAuth:
    def test_401_no_key(self, anon_client, channel):
        resp = anon_client.post(
            f"/api/contact-forms/v2/{channel.idx}/submit/",
            {"email": "test@example.com"},
            format="json",
        )
        assert resp.status_code == 401

    def test_401_wrong_key(self, channel):
        client = APIClient()
        client.credentials(HTTP_X_API_KEY="wrong-key-value")
        resp = client.post(
            f"/api/contact-forms/v2/{channel.idx}/submit/",
            {"email": "test@example.com"},
            format="json",
        )
        assert resp.status_code == 401

    def test_201_valid_key(self, authed_client, channel):
        resp = authed_client.post(
            f"/api/contact-forms/v2/{channel.idx}/submit/",
            {"email": "test@example.com"},
            format="json",
        )
        assert resp.status_code == 201


# === Submit Tests ===


@pytest.mark.django_db
class TestPublicSubmit:
    def test_submit_basic(self, authed_client, channel):
        resp = authed_client.post(
            f"/api/contact-forms/v2/{channel.idx}/submit/",
            {
                "email": "customer@example.com",
                "body": {"message": "Hello"},
                "slug": "contact-us",
                "code": "PROMO1",
            },
            format="json",
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["email"] == "customer@example.com"
        assert data["channel_idx"] == channel.idx
        assert data["slug"] == "contact-us"
        assert data["body"] == {"message": "Hello"}
        assert len(data["id"]) == 12

    def test_submit_with_type_id(self, authed_client, channel):
        FormTypeFactory(channel=channel, code="complaint")
        resp = authed_client.post(
            f"/api/contact-forms/v2/{channel.idx}/submit/complaint/",
            {"email": "customer@example.com"},
            format="json",
        )
        assert resp.status_code == 201
        assert resp.json()["type"] == "complaint"

    def test_submit_with_form_type_in_body_field(self, authed_client, channel):
        FormTypeFactory(channel=channel, code="product")
        resp = authed_client.post(
            f"/api/contact-forms/v2/{channel.idx}/submit/",
            {"email": "customer@example.com", "form_type": "product"},
            format="json",
        )
        assert resp.status_code == 201
        assert resp.json()["type"] == "product"

    def test_submit_unknown_type_falls_back_to_default(self, authed_client, channel):
        FormTypeFactory(channel=channel, code="default", is_default=True)
        resp = authed_client.post(
            f"/api/contact-forms/v2/{channel.idx}/submit/",
            {"email": "customer@example.com", "form_type": "does-not-exist"},
            format="json",
        )
        assert resp.status_code == 201
        assert resp.json()["type"] == "default"

    def test_submit_missing_email_returns_400(self, authed_client, channel):
        resp = authed_client.post(
            f"/api/contact-forms/v2/{channel.idx}/submit/",
            {"body": {"message": "no email"}},
            format="json",
        )
        assert resp.status_code == 400

    def test_submit_invalid_email_returns_400(self, authed_client, channel):
        resp = authed_client.post(
            f"/api/contact-forms/v2/{channel.idx}/submit/",
            {"email": "not-an-email"},
            format="json",
        )
        assert resp.status_code == 400

    def test_submit_channel_not_found(self, api_key):
        client = APIClient()
        client.credentials(HTTP_X_API_KEY=api_key.key)
        resp = client.post(
            "/api/contact-forms/v2/nonexistent-channel/submit/",
            {"email": "test@example.com"},
            format="json",
        )
        assert resp.status_code == 401  # APIKeyAuthentication raises AuthenticationFailed

    def test_submit_with_multipart(self, authed_client, channel):
        import io

        file_content = io.BytesIO(b"test file content")
        file_content.name = "test.txt"

        resp = authed_client.post(
            f"/api/contact-forms/v2/{channel.idx}/submit/",
            {
                "email": "customer@example.com",
                "body": '{"message": "with file"}',
                "file1": file_content,
            },
            format="multipart",
        )
        assert resp.status_code == 201

    # --- LeadCreationRule integration ---

    def test_submit_no_rule_does_not_create_lead(self, authed_client, channel):
        resp = authed_client.post(
            f"/api/contact-forms/v2/{channel.idx}/submit/",
            {"email": "customer@example.com"},
            format="json",
        )
        assert resp.status_code == 201
        assert Lead.objects.count() == 0

    def test_submit_with_matching_rule_creates_lead(self, authed_client, channel):
        FormTypeFactory(channel=channel, code="quote")
        LeadCreationRuleFactory(channel=channel, form_type="quote", slug="", enabled=True)
        resp = authed_client.post(
            f"/api/contact-forms/v2/{channel.idx}/submit/quote/",
            {"email": "lead@example.com"},
            format="json",
        )
        assert resp.status_code == 201
        assert Lead.objects.count() == 1
        lead = Lead.objects.get()
        assert lead.contact_form_id == resp.json()["id"]
        assert lead.email == "lead@example.com"
        assert lead.source_type == Lead.SourceType.FORM

    def test_submit_with_disabled_rule_does_not_create_lead(self, authed_client, channel):
        LeadCreationRuleFactory(channel=channel, form_type="quote", slug="", enabled=False)
        resp = authed_client.post(
            f"/api/contact-forms/v2/{channel.idx}/submit/quote/",
            {"email": "lead@example.com"},
            format="json",
        )
        assert resp.status_code == 201
        assert Lead.objects.count() == 0

    def test_submit_pulls_gclid_and_utm_from_body(self, authed_client, channel):
        FormTypeFactory(channel=channel, code="quote")
        LeadCreationRuleFactory(channel=channel, form_type="quote", slug="", enabled=True)
        resp = authed_client.post(
            f"/api/contact-forms/v2/{channel.idx}/submit/quote/",
            {
                "email": "lead@example.com",
                "body": {
                    "name": "Ada Lovelace",
                    "gclid": "CjwKEXAMPLE",
                    "utm_campaign": "spring-promo",
                    "utm_source": "google",
                    "utm_medium": "cpc",
                },
            },
            format="json",
        )
        assert resp.status_code == 201
        lead = Lead.objects.get()
        assert lead.name == "Ada Lovelace"
        assert lead.gclid == "CjwKEXAMPLE"
        assert lead.campaign_name == "spring-promo"
        assert lead.source == "google"
        assert lead.medium == "cpc"
        assert lead.attribution_method == Lead.AttributionMethod.GCLID

    def test_submit_rule_source_type_passthrough(self, authed_client, channel):
        FormTypeFactory(channel=channel, code="whatsapp-form")
        LeadCreationRuleFactory(
            channel=channel,
            form_type="whatsapp-form",
            slug="",
            enabled=True,
            source_type=Lead.SourceType.WHATSAPP,
        )
        resp = authed_client.post(
            f"/api/contact-forms/v2/{channel.idx}/submit/whatsapp-form/",
            {"email": "lead@example.com"},
            format="json",
        )
        assert resp.status_code == 201
        assert Lead.objects.get().source_type == Lead.SourceType.WHATSAPP

    def test_submit_rule_matches_resolved_type_from_body(self, authed_client, channel):
        """Storefront path: type in body, no type_id in URL — rule must match the resolved type."""
        FormTypeFactory(channel=channel, code="product")
        LeadCreationRuleFactory(channel=channel, form_type="product", slug="", enabled=True)
        resp = authed_client.post(
            f"/api/contact-forms/v2/{channel.idx}/submit/",
            {"email": "lead@example.com", "form_type": "product"},
            format="json",
        )
        assert resp.status_code == 201
        assert Lead.objects.count() == 1
        assert Lead.objects.get().contact_form.type == "product"


# === Client copy gating (config x body.send_copy) ===

_DISPATCH = "django_contact_forms.api.public.views.notification_service.dispatch_email"


@pytest.mark.django_db
class TestClientCopyDispatch:
    @pytest.mark.parametrize(
        "config_copy,body_copy,expected",
        [
            (True, True, True),
            (True, False, False),
            (False, True, False),
            (False, False, False),
        ],
    )
    def test_client_copy_gated_by_config_and_body(self, authed_client, channel, config_copy, body_copy, expected):
        FormNotificationConfigFactory(
            channel=channel, form_type="", slug="", send_email=True, send_client_copy=config_copy
        )
        with patch(_DISPATCH) as dispatch:
            resp = authed_client.post(
                f"/api/contact-forms/v2/{channel.idx}/submit/",
                {"email": "customer@example.com", "body": {"send_copy": body_copy}},
                format="json",
            )
        assert resp.status_code == 201
        dispatch.assert_called_once()
        assert dispatch.call_args.kwargs["send_client_copy"] is expected


# === Form types endpoint ===


@pytest.mark.django_db
class TestPublicFormTypes:
    def test_list_returns_channel_types(self, authed_client, channel):
        FormTypeFactory(channel=channel, code="general", is_default=True)
        FormTypeFactory(channel=channel, code="product")
        FormTypeFactory(channel=ChannelFactory(), code="other")  # different channel, excluded

        resp = authed_client.get(f"/api/contact-forms/v2/{channel.idx}/form-types/")
        assert resp.status_code == 200
        codes = {r["code"] for r in resp.json()["results"]}
        assert codes == {"general", "product"}

    def test_requires_api_key(self, anon_client, channel):
        resp = anon_client.get(f"/api/contact-forms/v2/{channel.idx}/form-types/")
        assert resp.status_code == 401


# === Throttle wiring ===


class TestSubmitThrottle:
    def test_submit_view_has_throttle(self):
        from django_contact_forms.api.public.throttling import ContactFormSubmitThrottle
        from django_contact_forms.api.public.views import SubmitViewSet

        assert ContactFormSubmitThrottle in SubmitViewSet.throttle_classes

    def test_throttle_rate_safety_net(self):
        from django_contact_forms.api.public.throttling import ContactFormSubmitThrottle

        # Even with no DEFAULT_THROTTLE_RATES entry, get_rate must return a rate.
        assert ContactFormSubmitThrottle().get_rate()
