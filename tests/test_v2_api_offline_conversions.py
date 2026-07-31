# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Admin v2 API: offline conversions (list/retrieve/retry)."""

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from django_contact_forms.models import Lead, OfflineConversionQueue
from django_contact_forms.services.conversions import queue_service
from tests.factories import ContactFormFactory, GoogleAdsConfigFactory, LeadFactory, enable_global_settings

User = get_user_model()


@pytest.fixture
def admin_client(db):
    user = User.objects.create_superuser(username="admin", password="x", email="a@x.com")
    token = str(RefreshToken.for_user(user).access_token)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return client


def _enqueue_one() -> OfflineConversionQueue:
    enable_global_settings(google_ads=True)
    cf = ContactFormFactory()
    GoogleAdsConfigFactory(channel=cf.channel)
    lead = LeadFactory(contact_form=cf, source_type=Lead.SourceType.CALENDAR, gclid="abc")
    queue_service.enqueue_for_lead(lead=lead, old_status=None, new_status=Lead.Status.NEW)
    return OfflineConversionQueue.objects.get()


@pytest.mark.django_db
def test_list_requires_auth():
    resp = APIClient().get("/api/contact-forms/v2/admin/offline-conversions/")
    assert resp.status_code == 401


@pytest.mark.django_db
def test_list_returns_rows(admin_client):
    _enqueue_one()
    resp = admin_client.get("/api/contact-forms/v2/admin/offline-conversions/")
    assert resp.status_code == 200
    assert resp.json()["count"] == 1


@pytest.mark.django_db
def test_list_filters_by_status(admin_client):
    _enqueue_one()
    resp = admin_client.get("/api/contact-forms/v2/admin/offline-conversions/?status=pending")
    assert resp.json()["count"] == 1
    resp_failed = admin_client.get("/api/contact-forms/v2/admin/offline-conversions/?status=failed")
    assert resp_failed.json()["count"] == 0


@pytest.mark.django_db
def test_retry_resets_to_pending(admin_client):
    row = _enqueue_one()
    queue_service.mark_failed(queue_id=row.pk, error="boom")
    row.refresh_from_db()
    assert row.status == OfflineConversionQueue.Status.FAILED
    resp = admin_client.post(f"/api/contact-forms/v2/admin/offline-conversions/{row.pk}/retry/")
    assert resp.status_code == 200
    assert resp.json()["status"] == OfflineConversionQueue.Status.PENDING


@pytest.mark.django_db
def test_retrieve_404(admin_client):
    resp = admin_client.get("/api/contact-forms/v2/admin/offline-conversions/999999/")
    assert resp.status_code == 404
