# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Lead lifecycle: create, update, status transition. Sends lead_status_changed signal."""

import hashlib
from decimal import Decimal
from typing import Any

from django.db import transaction
from django.db.models import Count, QuerySet
from django.utils import timezone

from django_contact_forms.models import ContactForm, Lead
from django_contact_forms.services.exceptions import InvalidLeadTransitionError
from django_contact_forms.signals import lead_status_changed

# Whitelist of allowed transitions. Re-opening from terminal states is allowed
# (sales reality — a "lost" deal can come back) but never silently.
_ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    Lead.Status.NEW: {Lead.Status.CONTACTED, Lead.Status.UNQUALIFIED},
    Lead.Status.CONTACTED: {Lead.Status.QUALIFIED, Lead.Status.UNQUALIFIED},
    Lead.Status.QUALIFIED: {Lead.Status.WON, Lead.Status.LOST},
    Lead.Status.UNQUALIFIED: {Lead.Status.NEW},
    Lead.Status.WON: {Lead.Status.LOST},
    Lead.Status.LOST: {Lead.Status.QUALIFIED, Lead.Status.WON},
}


@transaction.atomic
def create_lead(*, contact_form: ContactForm, source_type: str, **fields: Any) -> Lead:
    """Create a Lead from a ContactForm. Hashes email when no gclid is present."""
    lead = Lead(contact_form=contact_form, source_type=source_type, **fields)
    _hash_email_if_no_gclid(lead)
    lead.save()
    _send_status_signal(lead, old_status=None)
    return lead


_EDITABLE_FIELDS = frozenset({"name", "phone", "company", "deal_value", "notes"})


@transaction.atomic
def update_lead(*, lead: Lead, updates: dict[str, Any]) -> Lead:
    """Patch editable fields only. Refuses anything outside the whitelist.

    Mass-assignment defense: even if the API view's Pydantic schema later
    grows new fields, the service layer enforces what is actually editable.
    Status changes go through transition_status (and follow the FSM).
    """
    if "status" in updates:
        raise ValueError("Use transition_status() to change Lead.status, not update_lead()")
    invalid = set(updates) - _EDITABLE_FIELDS
    if invalid:
        raise ValueError(f"Fields not editable via update_lead: {sorted(invalid)}")
    for field, value in updates.items():
        setattr(lead, field, value)
    _hash_email_if_no_gclid(lead)
    lead.save()
    return lead


@transaction.atomic
def transition_status(*, lead: Lead, new_status: str, deal_value: Decimal | None = None) -> Lead:
    """Move Lead to a new status. Validates against the FSM, sends signal on success."""
    old_status = lead.status
    if new_status == old_status:
        return lead
    if new_status not in _ALLOWED_TRANSITIONS.get(old_status, set()):
        raise InvalidLeadTransitionError(f"Cannot transition Lead {lead.pk} from {old_status} to {new_status}")
    lead.status = new_status
    lead.status_changed_at = timezone.now()
    if deal_value is not None:
        lead.deal_value = deal_value
    lead.save(update_fields=["status", "status_changed_at", "deal_value", "modified_at"])
    _send_status_signal(lead, old_status=old_status)
    return lead


def list_leads(
    *,
    channel_idx: str | None = None,
    status: str | None = None,
    source_type: str | None = None,
    search: str | None = None,
) -> QuerySet[Lead]:
    """Bounded QuerySet for the admin list view. Caller paginates.

    Validates ``status`` and ``source_type`` against the model's TextChoices
    rather than passing user input through to ``.filter()`` — an unknown
    value would otherwise produce a ``FieldError`` 500 with field names
    leaked in the error.
    """
    if status and status not in Lead.Status.values:
        raise ValueError(f"Unknown status: {status!r}. Allowed: {sorted(Lead.Status.values)}")
    if source_type and source_type not in Lead.SourceType.values:
        raise ValueError(f"Unknown source_type: {source_type!r}. Allowed: {sorted(Lead.SourceType.values)}")
    qs = Lead.objects.select_related("contact_form", "contact_form__channel").order_by("-contact_date")
    if channel_idx:
        qs = qs.filter(contact_form__channel__idx=channel_idx)
    if status:
        qs = qs.filter(status=status)
    if source_type:
        qs = qs.filter(source_type=source_type)
    if search:
        qs = qs.filter(email__icontains=search) | qs.filter(name__icontains=search) | qs.filter(gclid__icontains=search)
    return qs


def get_lead(*, pk: int) -> Lead:
    return Lead.objects.select_related("contact_form", "contact_form__channel").get(pk=pk)


def summary_by_status(*, channel_idx: str | None = None) -> list[dict]:
    qs = Lead.objects.values("status").annotate(count=Count("id")).order_by("status")
    if channel_idx:
        qs = qs.filter(contact_form__channel__idx=channel_idx)
    return list(qs)


def _hash_email_if_no_gclid(lead: Lead) -> None:
    """Enhanced-conversions fallback. SHA-256 of lower-cased email when no gclid yet."""
    if lead.gclid or not lead.email or lead.hashed_email:
        return
    lead.hashed_email = hashlib.sha256(lead.email.lower().strip().encode()).hexdigest()


def _send_status_signal(lead: Lead, *, old_status: str | None) -> None:
    lead_status_changed.send(
        sender=Lead, lead=lead, old_status=old_status, new_status=lead.status, channel_idx=lead.contact_form.channel.idx
    )
