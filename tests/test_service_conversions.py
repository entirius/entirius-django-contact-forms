# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Conversions queue + uploader services."""

from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from django_contact_forms.models import Lead, OfflineConversionQueue
from django_contact_forms.services import lead_service
from django_contact_forms.services.conversions import google_ads_uploader, queue_service
from tests.factories import ContactFormFactory, GoogleAdsConfigFactory, LeadFactory, enable_global_settings


@pytest.mark.django_db
def test_kill_switch_off_no_enqueue():
    enable_global_settings(google_ads=False)
    lead = LeadFactory(gclid="abc")
    result = queue_service.enqueue_for_lead(lead=lead, old_status=None, new_status=Lead.Status.NEW)
    assert result is None
    assert OfflineConversionQueue.objects.count() == 0


@pytest.mark.django_db
def test_no_channel_config_no_enqueue():
    enable_global_settings(google_ads=True)
    lead = LeadFactory(gclid="abc")
    # No GoogleAdsConfig for this channel
    result = queue_service.enqueue_for_lead(lead=lead, old_status=None, new_status=Lead.Status.NEW)
    assert result is None


@pytest.mark.django_db
def test_calendar_lead_creation_enqueues_meeting_booked():
    enable_global_settings(google_ads=True)
    cf = ContactFormFactory()
    GoogleAdsConfigFactory(channel=cf.channel)
    lead = LeadFactory(contact_form=cf, source_type=Lead.SourceType.CALENDAR, gclid="abc")
    result = queue_service.enqueue_for_lead(lead=lead, old_status=None, new_status=Lead.Status.NEW)
    assert result is not None
    assert result.conversion_action_id == "9000000001"
    assert result.conversion_action_label == "Meeting Booked"
    assert result.status == OfflineConversionQueue.Status.PENDING
    assert result.gclid == "abc"


@pytest.mark.django_db
def test_form_lead_creation_does_not_enqueue():
    """Only calendar source type triggers the Meeting Booked event on creation."""
    enable_global_settings(google_ads=True)
    cf = ContactFormFactory()
    GoogleAdsConfigFactory(channel=cf.channel)
    lead = LeadFactory(contact_form=cf, source_type=Lead.SourceType.FORM, gclid="abc")
    result = queue_service.enqueue_for_lead(lead=lead, old_status=None, new_status=Lead.Status.NEW)
    assert result is None


@pytest.mark.django_db
def test_won_transition_enqueues_with_deal_value():
    enable_global_settings(google_ads=True)
    cf = ContactFormFactory()
    GoogleAdsConfigFactory(channel=cf.channel)
    lead = LeadFactory(contact_form=cf, gclid="abc", deal_value=Decimal("777.00"))
    result = queue_service.enqueue_for_lead(lead=lead, old_status=Lead.Status.QUALIFIED, new_status=Lead.Status.WON)
    assert result.conversion_action_label == "Won Deal"
    assert result.conversion_value == Decimal("777.00")


@pytest.mark.django_db
def test_no_gclid_no_hashed_email_marks_skipped():
    enable_global_settings(google_ads=True)
    cf = ContactFormFactory()
    GoogleAdsConfigFactory(channel=cf.channel)
    lead = LeadFactory(contact_form=cf, source_type=Lead.SourceType.CALENDAR, email="", gclid="")
    result = queue_service.enqueue_for_lead(lead=lead, old_status=None, new_status=Lead.Status.NEW)
    assert result.status == OfflineConversionQueue.Status.SKIPPED


@pytest.mark.django_db
def test_uniqueness_prevents_double_enqueue_for_same_action():
    enable_global_settings(google_ads=True)
    cf = ContactFormFactory()
    GoogleAdsConfigFactory(channel=cf.channel)
    lead = LeadFactory(contact_form=cf, source_type=Lead.SourceType.CALENDAR, gclid="abc")
    queue_service.enqueue_for_lead(lead=lead, old_status=None, new_status=Lead.Status.NEW)
    second = queue_service.enqueue_for_lead(lead=lead, old_status=Lead.Status.CONTACTED, new_status=Lead.Status.NEW)
    assert second is None  # get_or_create dedup
    assert OfflineConversionQueue.objects.filter(lead=lead).count() == 1


@pytest.mark.django_db
def test_signal_wiring_via_lead_service():
    """End-to-end through the signal: lead_service emits, handler enqueues."""
    enable_global_settings(google_ads=True)
    cf = ContactFormFactory()
    GoogleAdsConfigFactory(channel=cf.channel)
    lead_service.create_lead(contact_form=cf, source_type=Lead.SourceType.CALENDAR, email="a@b.com", gclid="abc")
    assert OfflineConversionQueue.objects.count() == 1


@pytest.mark.django_db
def test_uploader_no_pending_returns_zero():
    enable_global_settings(google_ads=True)
    cf = ContactFormFactory()
    GoogleAdsConfigFactory(channel=cf.channel)
    out = google_ads_uploader.upload_pending(channel_idx=cf.channel.idx)
    assert (out.imported, out.failed) == (0, 0)


@pytest.mark.django_db
def test_uploader_calls_sdk_and_marks_imported():
    enable_global_settings(google_ads=True)
    cf = ContactFormFactory()
    GoogleAdsConfigFactory(channel=cf.channel)
    lead = LeadFactory(contact_form=cf, source_type=Lead.SourceType.CALENDAR, gclid="abc")
    queue_service.enqueue_for_lead(lead=lead, old_status=None, new_status=Lead.Status.NEW)

    fake_client = MagicMock()
    fake_client.upload_click_conversions.return_value = MagicMock(failures=[])
    with patch("google_ads_sdk.ConversionsClient", return_value=fake_client):
        out = google_ads_uploader.upload_pending(channel_idx=cf.channel.idx)

    assert out.imported == 1
    assert out.failed == 0
    row = OfflineConversionQueue.objects.get()
    assert row.status == OfflineConversionQueue.Status.IMPORTED
    assert row.imported_at is not None
    lead.refresh_from_db()
    assert lead.ads_conversion_imported is True


@pytest.mark.django_db
def test_uploader_partial_failure_marks_failed_row():
    enable_global_settings(google_ads=True)
    cf = ContactFormFactory()
    GoogleAdsConfigFactory(channel=cf.channel)
    lead = LeadFactory(contact_form=cf, source_type=Lead.SourceType.CALENDAR, gclid="abc")
    queue_service.enqueue_for_lead(lead=lead, old_status=None, new_status=Lead.Status.NEW)

    failure = MagicMock(index=0, error_message="GCLID expired")
    fake_client = MagicMock()
    fake_client.upload_click_conversions.return_value = MagicMock(failures=[failure])
    with patch("google_ads_sdk.ConversionsClient", return_value=fake_client):
        out = google_ads_uploader.upload_pending(channel_idx=cf.channel.idx)

    assert (out.imported, out.failed) == (0, 1)
    row = OfflineConversionQueue.objects.get()
    assert row.status == OfflineConversionQueue.Status.FAILED
    assert "GCLID expired" in row.error_message
    assert row.attempt_count == 1
