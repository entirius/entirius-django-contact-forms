# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Tests for contact form services."""

import pytest

from django_contact_forms.models import Lead
from django_contact_forms.services import contact_form_service, lead_creation_rule_service, notification_service
from tests.factories import ChannelFactory, ContactFormFactory, FormNotificationConfigFactory, LeadCreationRuleFactory


@pytest.mark.django_db
class TestContactFormService:
    def test_list_submissions_returns_all(self):
        channel = ChannelFactory()
        ContactFormFactory.create_batch(3, channel=channel)

        qs = contact_form_service.list_submissions()
        assert qs.count() == 3

    def test_list_submissions_filter_by_channel(self):
        ch1 = ChannelFactory()
        ch2 = ChannelFactory()
        ContactFormFactory.create_batch(2, channel=ch1)
        ContactFormFactory(channel=ch2)

        qs = contact_form_service.list_submissions(channel_idx=ch1.idx)
        assert qs.count() == 2

    def test_list_submissions_filter_by_type(self):
        channel = ChannelFactory()
        ContactFormFactory(channel=channel, type="complaint")
        ContactFormFactory(channel=channel, type="general")

        qs = contact_form_service.list_submissions(form_type="complaint")
        assert qs.count() == 1

    def test_list_submissions_filter_by_slug(self):
        channel = ChannelFactory()
        ContactFormFactory(channel=channel, slug="contact-us")
        ContactFormFactory(channel=channel, slug="feedback")

        qs = contact_form_service.list_submissions(slug="feedback")
        assert qs.count() == 1

    def test_list_submissions_search_by_email(self):
        channel = ChannelFactory()
        ContactFormFactory(channel=channel, email="alice@example.com")
        ContactFormFactory(channel=channel, email="bob@example.com")

        qs = contact_form_service.list_submissions(search="alice")
        assert qs.count() == 1

    def test_get_submission(self):
        cf = ContactFormFactory()
        result = contact_form_service.get_submission(pk=cf.pk)
        assert result.email == cf.email

    def test_get_submission_not_found(self):
        from django.core.exceptions import ObjectDoesNotExist

        with pytest.raises(ObjectDoesNotExist):
            contact_form_service.get_submission(pk="999999999999")

    def test_create_submission(self):
        channel = ChannelFactory()
        cf = contact_form_service.create_submission(
            email="test@example.com",
            channel=channel,
            body={"msg": "hello"},
            slug="test-form",
            type_id="inquiry",
            code="CODE1",
        )
        assert cf.email == "test@example.com"
        assert cf.channel == channel
        assert cf.body == {"msg": "hello"}
        assert len(cf.id) == 12

    def test_get_attachments(self):
        from tests.factories import ContactFormAttachmentFactory

        cf = ContactFormFactory()
        ContactFormAttachmentFactory(contact_form=cf)
        ContactFormAttachmentFactory(contact_form=cf)

        attachments = contact_form_service.get_attachments(contact_form_pk=cf.pk)
        assert attachments.count() == 2


@pytest.mark.django_db
class TestNotificationService:
    def test_fallback_to_global_setting(self):
        channel = ChannelFactory()
        should_send, recipient = notification_service.should_send_email(channel)
        assert should_send is True
        assert recipient is None

    def test_channel_level_config(self):
        channel = ChannelFactory()
        FormNotificationConfigFactory(channel=channel, form_type="", slug="", send_email=False)

        should_send, _ = notification_service.should_send_email(channel)
        assert should_send is False

    def test_type_level_config(self):
        channel = ChannelFactory()
        FormNotificationConfigFactory(channel=channel, form_type="", slug="", send_email=True)
        FormNotificationConfigFactory(channel=channel, form_type="complaint", slug="", send_email=False)

        should_send, _ = notification_service.should_send_email(channel, form_type="complaint")
        assert should_send is False

    def test_exact_match_config(self):
        channel = ChannelFactory()
        FormNotificationConfigFactory(channel=channel, form_type="complaint", slug="", send_email=True)
        FormNotificationConfigFactory(
            channel=channel,
            form_type="complaint",
            slug="contact-us",
            send_email=False,
        )

        should_send, _ = notification_service.should_send_email(channel, form_type="complaint", slug="contact-us")
        assert should_send is False

    def test_fallback_chain_type_to_channel(self):
        channel = ChannelFactory()
        FormNotificationConfigFactory(
            channel=channel,
            form_type="",
            slug="",
            send_email=True,
            recipient_email="channel@example.com",
        )

        # No type-level config exists, should fall back to channel-level
        should_send, recipient = notification_service.should_send_email(channel, form_type="nonexistent")
        assert should_send is True
        assert recipient == "channel@example.com"

    def test_recipient_email_override(self):
        channel = ChannelFactory()
        FormNotificationConfigFactory(
            channel=channel,
            form_type="complaint",
            slug="",
            send_email=True,
            recipient_email="complaints@example.com",
        )

        should_send, recipient = notification_service.should_send_email(channel, form_type="complaint")
        assert should_send is True
        assert recipient == "complaints@example.com"

    def test_empty_recipient_returns_none(self):
        channel = ChannelFactory()
        FormNotificationConfigFactory(channel=channel, form_type="", slug="", send_email=True, recipient_email="")

        _, recipient = notification_service.should_send_email(channel)
        assert recipient is None


@pytest.mark.django_db
class TestUpdateConfig:
    def test_updates_editable_field(self):
        channel = ChannelFactory()
        config = FormNotificationConfigFactory(channel=channel, send_email=True)
        updated = notification_service.update_config(pk=config.pk, updates={"send_email": False})
        assert updated.send_email is False

    def test_updates_send_client_copy(self):
        channel = ChannelFactory()
        config = FormNotificationConfigFactory(channel=channel, send_client_copy=False)
        updated = notification_service.update_config(pk=config.pk, updates={"send_client_copy": True})
        assert updated.send_client_copy is True

    def test_rejects_non_whitelisted_field(self):
        channel = ChannelFactory()
        config = FormNotificationConfigFactory(channel=channel)
        with pytest.raises(ValueError, match="not editable"):
            notification_service.update_config(pk=config.pk, updates={"channel_id": 999})


@pytest.mark.django_db
class TestLeadCreationRuleService:
    # --- should_create_lead fallback chain ---

    def test_no_rule_is_off(self):
        channel = ChannelFactory()
        should, source = lead_creation_rule_service.should_create_lead(channel, form_type="quote", slug="contact-us")
        assert should is False
        assert source == Lead.SourceType.FORM

    def test_channel_level_enabled(self):
        channel = ChannelFactory()
        LeadCreationRuleFactory(channel=channel, form_type="", slug="", enabled=True, source_type=Lead.SourceType.FORM)
        should, source = lead_creation_rule_service.should_create_lead(channel)
        assert should is True
        assert source == Lead.SourceType.FORM

    def test_channel_level_disabled_blocks_lookup(self):
        channel = ChannelFactory()
        LeadCreationRuleFactory(channel=channel, form_type="", slug="", enabled=False)
        should, _ = lead_creation_rule_service.should_create_lead(channel, form_type="quote")
        assert should is False

    def test_type_level_overrides_channel_level(self):
        channel = ChannelFactory()
        LeadCreationRuleFactory(channel=channel, form_type="", slug="", enabled=False)
        LeadCreationRuleFactory(channel=channel, form_type="quote", slug="", enabled=True)
        should, _ = lead_creation_rule_service.should_create_lead(channel, form_type="quote")
        assert should is True

    def test_exact_match_overrides_type_level(self):
        channel = ChannelFactory()
        LeadCreationRuleFactory(channel=channel, form_type="quote", slug="", enabled=True)
        LeadCreationRuleFactory(channel=channel, form_type="quote", slug="contact-us", enabled=False)
        should, _ = lead_creation_rule_service.should_create_lead(channel, form_type="quote", slug="contact-us")
        assert should is False

    def test_source_type_passthrough(self):
        channel = ChannelFactory()
        LeadCreationRuleFactory(
            channel=channel,
            form_type="whatsapp-form",
            slug="",
            source_type=Lead.SourceType.WHATSAPP,
        )
        should, source = lead_creation_rule_service.should_create_lead(channel, form_type="whatsapp-form")
        assert should is True
        assert source == Lead.SourceType.WHATSAPP

    # --- extract_attribution ---

    def test_extract_attribution_none_body(self):
        assert lead_creation_rule_service.extract_attribution(None) == {}

    def test_extract_attribution_non_dict_body(self):
        assert lead_creation_rule_service.extract_attribution("just a string") == {}

    def test_extract_attribution_empty_dict(self):
        out = lead_creation_rule_service.extract_attribution({})
        assert out["raw_data"] == {}
        assert out["attribution_method"] == Lead.AttributionMethod.UNATTRIBUTED
        assert "gclid" not in out

    def test_extract_attribution_gclid_sets_method(self):
        body = {"gclid": "CjwK..."}
        out = lead_creation_rule_service.extract_attribution(body)
        assert out["gclid"] == "CjwK..."
        assert out["attribution_method"] == Lead.AttributionMethod.GCLID

    def test_extract_attribution_utm_mapping(self):
        body = {
            "utm_campaign": "spring-promo",
            "utm_source": "google",
            "utm_medium": "cpc",
        }
        out = lead_creation_rule_service.extract_attribution(body)
        assert out["campaign_name"] == "spring-promo"
        assert out["source"] == "google"
        assert out["medium"] == "cpc"

    def test_extract_attribution_contact_fields(self):
        body = {"name": "Ada", "phone": "+48", "company": "Analytical Engines"}
        out = lead_creation_rule_service.extract_attribution(body)
        assert out["name"] == "Ada"
        assert out["phone"] == "+48"
        assert out["company"] == "Analytical Engines"

    def test_extract_attribution_raw_data_preserves_full_body(self):
        body = {"name": "Ada", "custom_field": "keep me"}
        out = lead_creation_rule_service.extract_attribution(body)
        assert out["raw_data"] == body
