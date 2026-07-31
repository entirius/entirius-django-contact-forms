# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Admin v2 API: channel integrations (google_ads + bookings flags)."""

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from tests.factories import (
    BookingConfigFactory,
    ChannelFactory,
    GoogleAdsConfigFactory,
    enable_global_settings,
)

User = get_user_model()


@pytest.fixture
def admin_client(db):
    user = User.objects.create_superuser(username="admin", password="x", email="a@x.com")
    token = str(RefreshToken.for_user(user).access_token)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return client


@pytest.mark.django_db
def test_retrieve_requires_auth():
    from rest_framework.test import APIRequestFactory

    from django_contact_forms.api.admin.views.channel_integrations_views import (
        ChannelIntegrationsViewSet,
    )

    request = APIRequestFactory().get("/api/contact-forms/v2/admin/channels/x/integrations/")
    response = ChannelIntegrationsViewSet.as_view({"get": "retrieve"})(request, channel_idx="x")
    assert response.status_code == 401


@pytest.mark.django_db
def test_retrieve_forbidden_for_non_admin(db):
    from rest_framework.test import APIRequestFactory, force_authenticate

    from django_contact_forms.api.admin.views.channel_integrations_views import (
        ChannelIntegrationsViewSet,
    )

    user = User.objects.create_user(username="user", password="x", email="u@x.com")
    request = APIRequestFactory().get("/api/contact-forms/v2/admin/channels/x/integrations/")
    force_authenticate(request, user=user)
    response = ChannelIntegrationsViewSet.as_view({"get": "retrieve"})(request, channel_idx="x")
    assert response.status_code == 403


@pytest.mark.django_db
def test_retrieve_unknown_channel_returns_404(admin_client):
    resp = admin_client.get("/api/contact-forms/v2/admin/channels/missing-idx/integrations/")
    assert resp.status_code == 404


@pytest.mark.django_db
def test_both_enabled_when_global_and_per_channel_enabled(admin_client):
    channel = ChannelFactory()
    GoogleAdsConfigFactory(channel=channel, enabled=True)
    BookingConfigFactory(channel=channel, enabled=True)
    enable_global_settings(google_ads=True, bookings=True)

    resp = admin_client.get(f"/api/contact-forms/v2/admin/channels/{channel.idx}/integrations/")
    assert resp.status_code == 200
    body = resp.json()
    assert body["channel_idx"] == channel.idx
    assert body["google_ads_enabled"] is True
    assert body["bookings_enabled"] is True


@pytest.mark.django_db
def test_global_off_overrides_per_channel(admin_client):
    channel = ChannelFactory()
    GoogleAdsConfigFactory(channel=channel, enabled=True)
    BookingConfigFactory(channel=channel, enabled=True)
    enable_global_settings(google_ads=False, bookings=False)

    resp = admin_client.get(f"/api/contact-forms/v2/admin/channels/{channel.idx}/integrations/")
    body = resp.json()
    assert body["google_ads_enabled"] is False
    assert body["bookings_enabled"] is False


@pytest.mark.django_db
def test_per_channel_off_blocks_even_with_global_on(admin_client):
    channel = ChannelFactory()
    GoogleAdsConfigFactory(channel=channel, enabled=False)
    BookingConfigFactory(channel=channel, enabled=False)
    enable_global_settings(google_ads=True, bookings=True)

    resp = admin_client.get(f"/api/contact-forms/v2/admin/channels/{channel.idx}/integrations/")
    body = resp.json()
    assert body["google_ads_enabled"] is False
    assert body["bookings_enabled"] is False


@pytest.mark.django_db
def test_missing_per_channel_config_treated_as_disabled(admin_client):
    channel = ChannelFactory()  # no GoogleAdsConfig / BookingConfig rows
    enable_global_settings(google_ads=True, bookings=True)

    resp = admin_client.get(f"/api/contact-forms/v2/admin/channels/{channel.idx}/integrations/")
    body = resp.json()
    assert body["google_ads_enabled"] is False
    assert body["bookings_enabled"] is False
