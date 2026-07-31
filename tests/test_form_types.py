# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Tests for FormType model, type resolution, and client-copy gating."""

import pytest
from django.db import IntegrityError

from django_contact_forms.models import FormType
from django_contact_forms.services import contact_form_service, notification_service
from tests.factories import ChannelFactory, FormNotificationConfigFactory, FormTypeFactory


@pytest.mark.django_db
class TestFormTypeModel:
    def test_unique_code_per_channel(self):
        channel = ChannelFactory()
        FormTypeFactory(channel=channel, code="product")
        with pytest.raises(IntegrityError):
            FormType.objects.create(channel=channel, code="product")

    def test_same_code_allowed_on_different_channels(self):
        ch1 = ChannelFactory()
        ch2 = ChannelFactory()
        FormTypeFactory(channel=ch1, code="product")
        FormTypeFactory(channel=ch2, code="product")
        assert FormType.objects.filter(code="product").count() == 2

    def test_only_one_default_per_channel(self):
        channel = ChannelFactory()
        FormTypeFactory(channel=channel, code="default", is_default=True)
        with pytest.raises(IntegrityError):
            FormType.objects.create(channel=channel, code="general", is_default=True)


@pytest.mark.django_db
class TestResolveFormType:
    def test_known_form_type_field_wins(self):
        channel = ChannelFactory()
        FormTypeFactory(channel=channel, code="product")
        FormTypeFactory(channel=channel, code="general")
        resolved = contact_form_service.resolve_form_type(channel=channel, form_type="product", type_id="general")
        assert resolved == "product"

    def test_body_form_type_used_when_field_absent(self):
        channel = ChannelFactory()
        FormTypeFactory(channel=channel, code="product")
        resolved = contact_form_service.resolve_form_type(channel=channel, body={"form_type": "product"})
        assert resolved == "product"

    def test_legacy_body_type_alias(self):
        channel = ChannelFactory()
        FormTypeFactory(channel=channel, code="product")
        resolved = contact_form_service.resolve_form_type(channel=channel, body={"type": "product"})
        assert resolved == "product"

    def test_url_type_id_used_as_fallback(self):
        channel = ChannelFactory()
        FormTypeFactory(channel=channel, code="complaint")
        resolved = contact_form_service.resolve_form_type(channel=channel, type_id="complaint")
        assert resolved == "complaint"

    def test_unknown_type_falls_back_to_channel_default(self):
        channel = ChannelFactory()
        FormTypeFactory(channel=channel, code="default", is_default=True)
        FormTypeFactory(channel=channel, code="product")
        resolved = contact_form_service.resolve_form_type(channel=channel, form_type="nope")
        assert resolved == "default"

    def test_empty_type_falls_back_to_channel_default(self):
        channel = ChannelFactory()
        FormTypeFactory(channel=channel, code="default", is_default=True)
        resolved = contact_form_service.resolve_form_type(channel=channel)
        assert resolved == "default"

    def test_no_default_falls_back_to_settings_default(self):
        channel = ChannelFactory()  # no FormType rows at all
        resolved = contact_form_service.resolve_form_type(channel=channel, form_type="nope")
        assert resolved == "default"  # settings.CONTACT_FORM_DEFAULT_TYPE

    def test_non_scalar_body_type_does_not_raise(self):
        # Storefronts send arbitrary JSON; a list/dict type must coerce to the
        # default, never raise (regression: `candidate in set` on an unhashable).
        channel = ChannelFactory()
        FormTypeFactory(channel=channel, code="default", is_default=True)
        assert contact_form_service.resolve_form_type(channel=channel, body={"form_type": ["product"]}) == "default"
        assert contact_form_service.resolve_form_type(channel=channel, body={"type": {"x": 1}}) == "default"

    def test_create_submission_stores_resolved_type(self):
        channel = ChannelFactory()
        FormTypeFactory(channel=channel, code="product")
        cf = contact_form_service.create_submission(email="c@example.com", channel=channel, form_type="product")
        assert cf.type == "product"


@pytest.mark.django_db
class TestShouldSendClientCopy:
    def test_default_off_without_config(self):
        channel = ChannelFactory()
        assert notification_service.should_send_client_copy(channel) is False

    def test_channel_level_config(self):
        channel = ChannelFactory()
        FormNotificationConfigFactory(channel=channel, form_type="", slug="", send_client_copy=True)
        assert notification_service.should_send_client_copy(channel) is True

    def test_type_level_overrides_channel(self):
        channel = ChannelFactory()
        FormNotificationConfigFactory(channel=channel, form_type="", slug="", send_client_copy=False)
        FormNotificationConfigFactory(channel=channel, form_type="product", slug="", send_client_copy=True)
        assert notification_service.should_send_client_copy(channel, form_type="product") is True
