# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Admin v2 API: leads (list/retrieve/patch/transition/summary)."""

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from django_contact_forms.models import Lead
from django_contact_forms.services import lead_service
from tests.factories import ContactFormFactory, LeadFactory

User = get_user_model()


@pytest.fixture
def admin_client(db):
    user = User.objects.create_superuser(username="admin", password="x", email="a@x.com")
    token = str(RefreshToken.for_user(user).access_token)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return client


@pytest.fixture
def regular_client(db):
    user = User.objects.create_user(username="user", password="x", email="u@x.com")
    token = str(RefreshToken.for_user(user).access_token)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return client


@pytest.mark.django_db
def test_list_requires_auth():
    """Dispatch the view directly via APIRequestFactory — bypasses the URL resolver
    so the v1 legacy marshmallow_dataclass crash on Python 3.13 doesn't apply.
    Same security guarantee tested: unauthenticated requests get 401."""
    from rest_framework.test import APIRequestFactory

    from django_contact_forms.api.admin.views.lead_views import LeadViewSet

    request = APIRequestFactory().get("/api/contact-forms/v2/admin/leads/")
    response = LeadViewSet.as_view({"get": "list"})(request)
    assert response.status_code == 401


@pytest.mark.django_db
def test_list_forbidden_for_non_admin(db):
    """Same direct-dispatch pattern as test_list_requires_auth — bypass URL resolver
    to dodge the v1 marshmallow_dataclass crash on Python 3.13 in the local venv."""
    from rest_framework.test import APIRequestFactory, force_authenticate

    from django_contact_forms.api.admin.views.lead_views import LeadViewSet

    user = User.objects.create_user(username="user", password="x", email="u@x.com")
    request = APIRequestFactory().get("/api/contact-forms/v2/admin/leads/")
    force_authenticate(request, user=user)
    response = LeadViewSet.as_view({"get": "list"})(request)
    assert response.status_code == 403


@pytest.mark.django_db
def test_list_returns_leads(admin_client):
    LeadFactory.create_batch(3)
    resp = admin_client.get("/api/contact-forms/v2/admin/leads/")
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 3
    assert len(data["results"]) == 3


@pytest.mark.django_db
def test_list_filters_by_channel(admin_client):
    cf_a = ContactFormFactory()
    cf_b = ContactFormFactory()
    LeadFactory(contact_form=cf_a)
    LeadFactory(contact_form=cf_a)
    LeadFactory(contact_form=cf_b)
    resp = admin_client.get(f"/api/contact-forms/v2/admin/leads/?channel={cf_a.channel.idx}")
    assert resp.json()["count"] == 2


@pytest.mark.django_db
def test_retrieve_404(admin_client):
    resp = admin_client.get("/api/contact-forms/v2/admin/leads/999999/")
    assert resp.status_code == 404


@pytest.mark.django_db
def test_retrieve_returns_lead(admin_client):
    lead = LeadFactory()
    resp = admin_client.get(f"/api/contact-forms/v2/admin/leads/{lead.pk}/")
    assert resp.status_code == 200
    assert resp.json()["id"] == lead.pk


@pytest.mark.django_db
def test_patch_updates_editable_fields(admin_client):
    lead = LeadFactory()
    resp = admin_client.patch(
        f"/api/contact-forms/v2/admin/leads/{lead.pk}/",
        {"name": "Updated", "phone": "+48123", "notes": "Hello"},
        format="json",
    )
    assert resp.status_code == 200
    lead.refresh_from_db()
    assert lead.name == "Updated"
    assert lead.phone == "+48123"
    assert lead.notes == "Hello"


@pytest.mark.django_db
def test_transition_valid_path(admin_client):
    lead = LeadFactory(status=Lead.Status.NEW)
    resp = admin_client.post(
        f"/api/contact-forms/v2/admin/leads/{lead.pk}/transition/", {"new_status": Lead.Status.CONTACTED}, format="json"
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == Lead.Status.CONTACTED


@pytest.mark.django_db
def test_transition_disallowed_returns_400(admin_client):
    lead = LeadFactory(status=Lead.Status.NEW)
    resp = admin_client.post(
        f"/api/contact-forms/v2/admin/leads/{lead.pk}/transition/", {"new_status": Lead.Status.WON}, format="json"
    )
    assert resp.status_code == 400
    body = resp.json()
    # Structured error response (per code-review C24): error code + from/to + message,
    # not a flat `detail` string.
    assert body["error"] == "INVALID_TRANSITION"
    assert body["from_status"] == Lead.Status.NEW
    assert body["to_status"] == Lead.Status.WON
    assert "Cannot transition" in body["message"]


@pytest.mark.django_db
def test_summary_aggregates_by_status(admin_client):
    LeadFactory()  # NEW
    contacted = LeadFactory()
    lead_service.transition_status(lead=contacted, new_status=Lead.Status.CONTACTED)
    resp = admin_client.get("/api/contact-forms/v2/admin/leads/summary/")
    assert resp.status_code == 200
    by_status = {row["status"]: row["count"] for row in resp.json()["by_status"]}
    assert by_status[Lead.Status.NEW] == 1
    assert by_status[Lead.Status.CONTACTED] == 1
