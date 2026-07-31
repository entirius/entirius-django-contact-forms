# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Admin v2 API: bookings (list/retrieve)."""

from datetime import UTC, datetime, timedelta

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from django_contact_forms.models import Lead
from tests.factories import BookingFactory, ContactFormFactory, LeadFactory

User = get_user_model()


@pytest.fixture
def admin_client(db):
    user = User.objects.create_superuser(username="admin", password="x", email="a@x.com")
    token = str(RefreshToken.for_user(user).access_token)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return client


@pytest.mark.django_db
def test_list_requires_auth():
    """Direct ViewSet dispatch — mirrors the lead-test pattern to dodge the
    v1 marshmallow_dataclass URL-resolver crash on Python 3.13."""
    from rest_framework.test import APIRequestFactory

    from django_contact_forms.api.admin.views.booking_views import BookingViewSet

    request = APIRequestFactory().get("/api/contact-forms/v2/admin/bookings/")
    response = BookingViewSet.as_view({"get": "list"})(request)
    assert response.status_code == 401


@pytest.mark.django_db
def test_list_forbidden_for_non_admin(db):
    from rest_framework.test import APIRequestFactory, force_authenticate

    from django_contact_forms.api.admin.views.booking_views import BookingViewSet

    user = User.objects.create_user(username="user", password="x", email="u@x.com")
    request = APIRequestFactory().get("/api/contact-forms/v2/admin/bookings/")
    force_authenticate(request, user=user)
    response = BookingViewSet.as_view({"get": "list"})(request)
    assert response.status_code == 403


@pytest.mark.django_db
def test_list_returns_bookings(admin_client):
    BookingFactory.create_batch(3)
    resp = admin_client.get("/api/contact-forms/v2/admin/bookings/")
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 3
    assert len(data["results"]) == 3


@pytest.mark.django_db
def test_list_filters_by_channel(admin_client):
    cf_a = ContactFormFactory()
    cf_b = ContactFormFactory()
    BookingFactory(contact_form=cf_a)
    BookingFactory(contact_form=ContactFormFactory(channel=cf_a.channel))
    BookingFactory(contact_form=cf_b)
    resp = admin_client.get(f"/api/contact-forms/v2/admin/bookings/?channel={cf_a.channel.idx}")
    assert resp.json()["count"] == 2


@pytest.mark.django_db
def test_list_filters_by_date_range(admin_client):
    now = datetime.now(UTC)
    BookingFactory(meeting_start=now - timedelta(days=2), meeting_end=now - timedelta(days=2))
    in_range = BookingFactory(meeting_start=now + timedelta(days=1), meeting_end=now + timedelta(days=1))
    BookingFactory(meeting_start=now + timedelta(days=10), meeting_end=now + timedelta(days=10))

    resp = admin_client.get(
        "/api/contact-forms/v2/admin/bookings/",
        {
            "date_from": (now - timedelta(days=1)).isoformat(),
            "date_to": (now + timedelta(days=5)).isoformat(),
        },
    )
    body = resp.json()
    assert resp.status_code == 200, body
    assert body["count"] == 1
    assert body["results"][0]["id"] == in_range.pk


@pytest.mark.django_db
def test_list_invalid_date_returns_400(admin_client):
    resp = admin_client.get("/api/contact-forms/v2/admin/bookings/?date_from=not-a-date")
    assert resp.status_code == 400


@pytest.mark.django_db
def test_list_filters_by_lead_status(admin_client):
    cf_won = ContactFormFactory()
    BookingFactory(contact_form=cf_won)
    LeadFactory(contact_form=cf_won, status=Lead.Status.WON)

    cf_new = ContactFormFactory()
    BookingFactory(contact_form=cf_new)
    LeadFactory(contact_form=cf_new, status=Lead.Status.NEW)

    resp = admin_client.get(f"/api/contact-forms/v2/admin/bookings/?lead_status={Lead.Status.WON}")
    body = resp.json()
    assert body["count"] == 1
    assert body["results"][0]["linked_lead"]["status"] == Lead.Status.WON


@pytest.mark.django_db
def test_list_invalid_lead_status_returns_400(admin_client):
    resp = admin_client.get("/api/contact-forms/v2/admin/bookings/?lead_status=bogus")
    assert resp.status_code == 400


@pytest.mark.django_db
def test_list_search_by_email(admin_client):
    alice = ContactFormFactory(email="alice@example.com")
    BookingFactory(contact_form=alice)
    bob = ContactFormFactory(email="bob@example.com")
    BookingFactory(contact_form=bob)
    resp = admin_client.get("/api/contact-forms/v2/admin/bookings/?search=alice")
    assert resp.json()["count"] == 1


@pytest.mark.django_db
def test_retrieve_404(admin_client):
    resp = admin_client.get("/api/contact-forms/v2/admin/bookings/999999/")
    assert resp.status_code == 404


@pytest.mark.django_db
def test_retrieve_returns_booking_with_name_from_body(admin_client):
    cf = ContactFormFactory(body={"name": "Ada Lovelace"})
    booking = BookingFactory(contact_form=cf)
    resp = admin_client.get(f"/api/contact-forms/v2/admin/bookings/{booking.pk}/")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == booking.pk
    assert body["name"] == "Ada Lovelace"
    assert body["email"] == cf.email
    assert body["channel_idx"] == cf.channel.idx
    assert body["linked_lead"] is None


@pytest.mark.django_db
def test_retrieve_embeds_most_recent_linked_lead(admin_client):
    """A ContactForm can spawn more than one Lead over time; surface the newest."""
    cf = ContactFormFactory(body={"name": "Grace Hopper"})
    booking = BookingFactory(contact_form=cf)
    older = LeadFactory(contact_form=cf, name="old", status=Lead.Status.UNQUALIFIED)
    newer = LeadFactory(contact_form=cf, name="new", status=Lead.Status.QUALIFIED)

    # Force contact_date ordering so "newer" is actually later
    newer.contact_date = older.contact_date + timedelta(hours=1)
    newer.save(update_fields=["contact_date"])

    resp = admin_client.get(f"/api/contact-forms/v2/admin/bookings/{booking.pk}/")
    body = resp.json()
    assert body["linked_lead"]["id"] == newer.pk
    assert body["linked_lead"]["status"] == Lead.Status.QUALIFIED
