# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Tests for v2 Admin API endpoints."""

import pytest
from django.contrib.auth.models import User
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from tests.factories import (
    ChannelFactory,
    ContactFormAttachmentFactory,
    ContactFormFactory,
    FormNotificationConfigFactory,
    FormTypeFactory,
)


@pytest.fixture
def admin_user(db):
    return User.objects.create_superuser(username="admin", email="admin@test.com", password="admin123")


@pytest.fixture
def regular_user(db):
    return User.objects.create_user(username="regular", email="regular@test.com", password="regular123")


@pytest.fixture
def admin_client(admin_user):
    client = APIClient()
    token = RefreshToken.for_user(admin_user).access_token
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return client


@pytest.fixture
def regular_client(regular_user):
    client = APIClient()
    token = RefreshToken.for_user(regular_user).access_token
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return client


@pytest.fixture
def anon_client():
    return APIClient()


# === Auth Tests ===


@pytest.mark.django_db
class TestSubmissionAuth:
    def test_401_no_token(self, anon_client):
        resp = anon_client.get("/api/contact-forms/v2/admin/submissions/")
        assert resp.status_code == 401

    def test_403_regular_user(self, regular_client):
        resp = regular_client.get("/api/contact-forms/v2/admin/submissions/")
        assert resp.status_code == 403

    def test_200_admin_user(self, admin_client):
        resp = admin_client.get("/api/contact-forms/v2/admin/submissions/")
        assert resp.status_code == 200


# === Submission List Tests ===


@pytest.mark.django_db
class TestSubmissionList:
    def test_list_returns_paginated(self, admin_client):
        channel = ChannelFactory()
        ContactFormFactory.create_batch(3, channel=channel)

        resp = admin_client.get("/api/contact-forms/v2/admin/submissions/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 3
        assert len(data["results"]) == 3
        assert "next" in data
        assert "previous" in data

    def test_list_filter_by_type(self, admin_client):
        channel = ChannelFactory()
        ContactFormFactory(channel=channel, type="complaint")
        ContactFormFactory(channel=channel, type="general")

        resp = admin_client.get("/api/contact-forms/v2/admin/submissions/?type=complaint")
        assert resp.status_code == 200
        assert resp.json()["count"] == 1

    def test_list_filter_by_slug(self, admin_client):
        channel = ChannelFactory()
        ContactFormFactory(channel=channel, slug="feedback")
        ContactFormFactory(channel=channel, slug="contact-us")

        resp = admin_client.get("/api/contact-forms/v2/admin/submissions/?slug=feedback")
        assert resp.json()["count"] == 1

    def test_list_filter_by_channel(self, admin_client):
        ch1 = ChannelFactory()
        ch2 = ChannelFactory()
        ContactFormFactory.create_batch(2, channel=ch1)
        ContactFormFactory(channel=ch2)

        resp = admin_client.get(f"/api/contact-forms/v2/admin/submissions/?channel={ch1.idx}")
        assert resp.json()["count"] == 2

    def test_list_search_by_email(self, admin_client):
        channel = ChannelFactory()
        ContactFormFactory(channel=channel, email="alice@example.com")
        ContactFormFactory(channel=channel, email="bob@example.com")

        resp = admin_client.get("/api/contact-forms/v2/admin/submissions/?search=alice")
        assert resp.json()["count"] == 1

    def test_list_invalid_ordering(self, admin_client):
        resp = admin_client.get("/api/contact-forms/v2/admin/submissions/?ordering=invalid")
        assert resp.status_code == 400

    def test_list_pagination(self, admin_client):
        channel = ChannelFactory()
        ContactFormFactory.create_batch(25, channel=channel)

        resp = admin_client.get("/api/contact-forms/v2/admin/submissions/")
        data = resp.json()
        assert data["count"] == 25
        assert len(data["results"]) == 20  # page_size default
        assert data["next"] is not None

    def test_list_page_size(self, admin_client):
        channel = ChannelFactory()
        ContactFormFactory.create_batch(5, channel=channel)

        resp = admin_client.get("/api/contact-forms/v2/admin/submissions/?page_size=2")
        data = resp.json()
        assert len(data["results"]) == 2


# === Submission Retrieve Tests ===


@pytest.mark.django_db
class TestSubmissionRetrieve:
    def test_retrieve_returns_detail(self, admin_client):
        cf = ContactFormFactory()

        resp = admin_client.get(f"/api/contact-forms/v2/admin/submissions/{cf.pk}/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == cf.pk
        assert data["email"] == cf.email
        assert data["channel_idx"] == cf.channel.idx
        assert "attachments" in data
        assert "body" in data
        assert "created_at" in data

    def test_retrieve_with_attachments(self, admin_client):
        cf = ContactFormFactory()
        ContactFormAttachmentFactory(contact_form=cf)
        ContactFormAttachmentFactory(contact_form=cf)

        resp = admin_client.get(f"/api/contact-forms/v2/admin/submissions/{cf.pk}/")
        data = resp.json()
        assert len(data["attachments"]) == 2

    def test_retrieve_not_found(self, admin_client):
        resp = admin_client.get("/api/contact-forms/v2/admin/submissions/999999999999/")
        assert resp.status_code == 404


# === Notification Config CRUD Tests ===


@pytest.mark.django_db
class TestNotificationConfigAuth:
    def test_401_no_token(self, anon_client):
        resp = anon_client.get("/api/contact-forms/v2/admin/notifications/")
        assert resp.status_code == 401

    def test_403_regular_user(self, regular_client):
        resp = regular_client.get("/api/contact-forms/v2/admin/notifications/")
        assert resp.status_code == 403

    def test_200_admin_user(self, admin_client):
        resp = admin_client.get("/api/contact-forms/v2/admin/notifications/")
        assert resp.status_code == 200


@pytest.mark.django_db
class TestNotificationConfigCRUD:
    def test_list(self, admin_client):
        channel = ChannelFactory()
        FormNotificationConfigFactory(channel=channel)

        resp = admin_client.get("/api/contact-forms/v2/admin/notifications/")
        assert resp.status_code == 200
        assert resp.json()["count"] == 1

    def test_list_filter_by_channel(self, admin_client):
        ch1 = ChannelFactory()
        ch2 = ChannelFactory()
        FormNotificationConfigFactory(channel=ch1)
        FormNotificationConfigFactory(channel=ch2)

        resp = admin_client.get(f"/api/contact-forms/v2/admin/notifications/?channel={ch1.idx}")
        assert resp.json()["count"] == 1

    def test_create(self, admin_client):
        channel = ChannelFactory()

        resp = admin_client.post(
            "/api/contact-forms/v2/admin/notifications/",
            {
                "channel_id": channel.pk,
                "form_type": "complaint",
                "slug": "",
                "send_email": True,
                "recipient_email": "complaints@example.com",
            },
            format="json",
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["channel_idx"] == channel.idx
        assert data["form_type"] == "complaint"
        assert data["recipient_email"] == "complaints@example.com"

    def test_create_duplicate_returns_400(self, admin_client):
        channel = ChannelFactory()
        FormNotificationConfigFactory(channel=channel, form_type="complaint", slug="")

        resp = admin_client.post(
            "/api/contact-forms/v2/admin/notifications/",
            {
                "channel_id": channel.pk,
                "form_type": "complaint",
                "slug": "",
            },
            format="json",
        )
        assert resp.status_code == 400

    def test_create_invalid_channel(self, admin_client):
        resp = admin_client.post(
            "/api/contact-forms/v2/admin/notifications/",
            {"channel_id": 9999},
            format="json",
        )
        assert resp.status_code == 400

    def test_retrieve(self, admin_client):
        config = FormNotificationConfigFactory()

        resp = admin_client.get(f"/api/contact-forms/v2/admin/notifications/{config.pk}/")
        assert resp.status_code == 200
        assert resp.json()["id"] == config.pk

    def test_retrieve_not_found(self, admin_client):
        resp = admin_client.get("/api/contact-forms/v2/admin/notifications/9999/")
        assert resp.status_code == 404

    def test_partial_update(self, admin_client):
        config = FormNotificationConfigFactory(send_email=True)

        resp = admin_client.patch(
            f"/api/contact-forms/v2/admin/notifications/{config.pk}/",
            {"send_email": False},
            format="json",
        )
        assert resp.status_code == 200
        assert resp.json()["send_email"] is False

    def test_delete(self, admin_client):
        config = FormNotificationConfigFactory()

        resp = admin_client.delete(f"/api/contact-forms/v2/admin/notifications/{config.pk}/")
        assert resp.status_code == 204

        resp = admin_client.get(f"/api/contact-forms/v2/admin/notifications/{config.pk}/")
        assert resp.status_code == 404

    def test_delete_not_found(self, admin_client):
        resp = admin_client.delete("/api/contact-forms/v2/admin/notifications/9999/")
        assert resp.status_code == 404


# === Submission Status Update Tests ===


@pytest.mark.django_db
class TestSubmissionStatusUpdate:
    def test_200_valid_status(self, admin_client):
        cf = ContactFormFactory()
        resp = admin_client.patch(
            f"/api/contact-forms/v2/admin/submissions/{cf.pk}/",
            {"status": "in_progress"},
            format="json",
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "in_progress"

    def test_400_invalid_status(self, admin_client):
        cf = ContactFormFactory()
        resp = admin_client.patch(
            f"/api/contact-forms/v2/admin/submissions/{cf.pk}/",
            {"status": "invalid_value"},
            format="json",
        )
        assert resp.status_code == 400

    def test_404_not_found(self, admin_client):
        resp = admin_client.patch(
            "/api/contact-forms/v2/admin/submissions/999999999999/",
            {"status": "done"},
            format="json",
        )
        assert resp.status_code == 404


# === Attachment Download Tests ===


@pytest.mark.django_db
class TestAttachmentDownload:
    def test_401_no_token(self, anon_client):
        resp = anon_client.get("/api/contact-forms/v2/admin/submissions/123456789012/attachments/1/download/")
        assert resp.status_code == 401

    def test_403_regular_user(self, regular_client):
        resp = regular_client.get("/api/contact-forms/v2/admin/submissions/123456789012/attachments/1/download/")
        assert resp.status_code == 403

    def test_200_file_response(self, admin_client):
        attachment = ContactFormAttachmentFactory()
        cf = attachment.contact_form
        resp = admin_client.get(
            f"/api/contact-forms/v2/admin/submissions/{cf.pk}/attachments/{attachment.pk}/download/"
        )
        assert resp.status_code == 200
        assert resp.get("Content-Disposition") is not None

    def test_404_attachment_not_in_db(self, admin_client):
        cf = ContactFormFactory()
        resp = admin_client.get(f"/api/contact-forms/v2/admin/submissions/{cf.pk}/attachments/9999/download/")
        assert resp.status_code == 404

    def test_404_file_missing_on_disk(self, admin_client):
        attachment = ContactFormAttachmentFactory()
        cf = attachment.contact_form
        attachment.attachment.delete(save=False)
        resp = admin_client.get(
            f"/api/contact-forms/v2/admin/submissions/{cf.pk}/attachments/{attachment.pk}/download/"
        )
        assert resp.status_code == 404


# === Form Types (admin) ===


@pytest.mark.django_db
class TestAdminFormTypes:
    def test_401_no_token(self, anon_client):
        resp = anon_client.get("/api/contact-forms/v2/admin/form-types/?channel_idx=x")
        assert resp.status_code == 401

    def test_403_regular_user(self, regular_client):
        resp = regular_client.get("/api/contact-forms/v2/admin/form-types/?channel_idx=x")
        assert resp.status_code == 403

    def test_lists_channel_types(self, admin_client):
        channel = ChannelFactory(idx="ch-ft")
        FormTypeFactory(channel=channel, code="general", is_default=True)
        FormTypeFactory(channel=channel, code="product")
        resp = admin_client.get(f"/api/contact-forms/v2/admin/form-types/?channel_idx={channel.idx}")
        assert resp.status_code == 200
        codes = {r["code"] for r in resp.json()["results"]}
        assert codes == {"general", "product"}

    def test_missing_channel_idx_returns_400(self, admin_client):
        resp = admin_client.get("/api/contact-forms/v2/admin/form-types/")
        assert resp.status_code == 400

    def test_unknown_channel_returns_400(self, admin_client):
        resp = admin_client.get("/api/contact-forms/v2/admin/form-types/?channel_idx=nope")
        assert resp.status_code == 400


# === Notification config: send_client_copy ===


@pytest.mark.django_db
class TestNotificationConfigClientCopy:
    def test_create_with_send_client_copy(self, admin_client):
        channel = ChannelFactory()
        resp = admin_client.post(
            "/api/contact-forms/v2/admin/notifications/",
            {
                "channel_id": channel.pk,
                "form_type": "product",
                "slug": "",
                "send_email": True,
                "send_client_copy": True,
                "recipient_email": "",
            },
            format="json",
        )
        assert resp.status_code == 201
        assert resp.json()["send_client_copy"] is True

    def test_patch_send_client_copy(self, admin_client):
        config = FormNotificationConfigFactory(send_client_copy=False)
        resp = admin_client.patch(
            f"/api/contact-forms/v2/admin/notifications/{config.pk}/",
            {"send_client_copy": True},
            format="json",
        )
        assert resp.status_code == 200
        assert resp.json()["send_client_copy"] is True
