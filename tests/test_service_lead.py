# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Lead service: creation, status FSM, signal emission, email hashing."""

from decimal import Decimal

import pytest

from django_contact_forms.models import Lead
from django_contact_forms.services import lead_service
from django_contact_forms.services.exceptions import InvalidLeadTransitionError
from django_contact_forms.signals import lead_status_changed
from tests.factories import ContactFormFactory


@pytest.mark.django_db
def test_create_lead_hashes_email_when_no_gclid():
    cf = ContactFormFactory()
    lead = lead_service.create_lead(contact_form=cf, source_type=Lead.SourceType.FORM, email="JOHN@Example.COM ")
    assert lead.hashed_email
    assert len(lead.hashed_email) == 64  # sha256 hex
    # Same input always hashes the same way
    import hashlib

    assert lead.hashed_email == hashlib.sha256(b"john@example.com").hexdigest()


@pytest.mark.django_db
def test_create_lead_skips_hash_when_gclid_present():
    cf = ContactFormFactory()
    lead = lead_service.create_lead(
        contact_form=cf, source_type=Lead.SourceType.FORM, email="x@y.com", gclid="CjwK-test"
    )
    assert lead.hashed_email == ""
    assert lead.gclid == "CjwK-test"


@pytest.mark.django_db
def test_create_lead_sends_signal_with_old_status_none():
    cf = ContactFormFactory()
    received: list[dict] = []

    def receiver(sender, lead, old_status, new_status, channel_idx, **kwargs):
        received.append({"old": old_status, "new": new_status, "channel": channel_idx})

    lead_status_changed.connect(receiver, dispatch_uid="test_lead_create")
    try:
        lead_service.create_lead(contact_form=cf, source_type=Lead.SourceType.FORM, email="a@b.com")
    finally:
        lead_status_changed.disconnect(dispatch_uid="test_lead_create")

    assert len(received) == 1
    assert received[0] == {"old": None, "new": Lead.Status.NEW, "channel": cf.channel.idx}


@pytest.mark.django_db
def test_transition_status_valid_path():
    cf = ContactFormFactory()
    lead = lead_service.create_lead(contact_form=cf, source_type=Lead.SourceType.FORM, email="a@b.com")
    lead = lead_service.transition_status(lead=lead, new_status=Lead.Status.CONTACTED)
    lead = lead_service.transition_status(lead=lead, new_status=Lead.Status.QUALIFIED)
    lead = lead_service.transition_status(lead=lead, new_status=Lead.Status.WON, deal_value=Decimal("1234.56"))
    lead.refresh_from_db()
    assert lead.status == Lead.Status.WON
    assert lead.deal_value == Decimal("1234.56")
    assert lead.status_changed_at is not None


@pytest.mark.django_db
def test_transition_status_disallowed_raises():
    cf = ContactFormFactory()
    lead = lead_service.create_lead(contact_form=cf, source_type=Lead.SourceType.FORM, email="a@b.com")
    with pytest.raises(InvalidLeadTransitionError):
        lead_service.transition_status(lead=lead, new_status=Lead.Status.WON)


@pytest.mark.django_db
def test_transition_to_same_status_is_noop():
    cf = ContactFormFactory()
    lead = lead_service.create_lead(contact_form=cf, source_type=Lead.SourceType.FORM, email="a@b.com")
    before = lead.status_changed_at
    lead = lead_service.transition_status(lead=lead, new_status=Lead.Status.NEW)
    assert lead.status_changed_at == before


@pytest.mark.django_db
def test_update_lead_refuses_status_field():
    cf = ContactFormFactory()
    lead = lead_service.create_lead(contact_form=cf, source_type=Lead.SourceType.FORM, email="a@b.com")
    with pytest.raises(ValueError):
        lead_service.update_lead(lead=lead, updates={"status": Lead.Status.WON})


@pytest.mark.django_db
def test_lost_lead_can_be_reopened():
    """Sales reality: a lost deal can come back. FSM allows LOST → QUALIFIED."""
    cf = ContactFormFactory()
    lead = lead_service.create_lead(contact_form=cf, source_type=Lead.SourceType.FORM, email="a@b.com")
    lead = lead_service.transition_status(lead=lead, new_status=Lead.Status.CONTACTED)
    lead = lead_service.transition_status(lead=lead, new_status=Lead.Status.QUALIFIED)
    lead = lead_service.transition_status(lead=lead, new_status=Lead.Status.LOST)
    lead = lead_service.transition_status(lead=lead, new_status=Lead.Status.QUALIFIED)
    assert lead.status == Lead.Status.QUALIFIED


@pytest.mark.django_db
def test_summary_by_status_aggregates_correctly():
    cf = ContactFormFactory()
    lead_service.create_lead(contact_form=cf, source_type=Lead.SourceType.FORM, email="a@b.com")
    l2 = lead_service.create_lead(contact_form=cf, source_type=Lead.SourceType.FORM, email="b@b.com")
    lead_service.transition_status(lead=l2, new_status=Lead.Status.CONTACTED)

    summary = lead_service.summary_by_status()
    by_status = {row["status"]: row["count"] for row in summary}
    assert by_status[Lead.Status.NEW] == 1
    assert by_status[Lead.Status.CONTACTED] == 1
