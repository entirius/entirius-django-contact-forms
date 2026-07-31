# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Map Lead status transitions to OfflineConversionQueue rows. No SDK calls here."""

import logging
from dataclasses import dataclass
from decimal import Decimal

from django.db.models import F, QuerySet
from django.utils import timezone

from django_contact_forms.models import GoogleAdsConfig, Lead, OfflineConversionQueue, is_google_ads_enabled

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _ConversionSpec:
    action_id: str
    label: str
    value: Decimal


def enqueue_for_lead(*, lead: Lead, old_status: str | None, new_status: str) -> OfflineConversionQueue | None:
    """Create a queue row for the (lead, conversion_action_id) if the rules say so. Idempotent on retry."""
    if not is_google_ads_enabled():
        return None
    if old_status == new_status:
        return None

    config = _get_active_config(lead)
    if config is None:
        return None

    spec = _spec_for_transition(config, lead, new_status)
    if spec is None or not spec.action_id:
        return None

    status = (
        OfflineConversionQueue.Status.PENDING
        if (lead.gclid or lead.hashed_email)
        else OfflineConversionQueue.Status.SKIPPED
    )
    obj, created = OfflineConversionQueue.objects.get_or_create(
        lead=lead,
        conversion_action_id=spec.action_id,
        defaults={
            "conversion_action_label": spec.label,
            "conversion_time": timezone.now(),
            "conversion_value": spec.value,
            "currency_code": config.default_currency_code,
            "gclid": lead.gclid or "",
            "hashed_email": lead.hashed_email or "",
            "status": status,
        },
    )
    return obj if created else None


def mark_imported(*, queue_id: int) -> None:
    OfflineConversionQueue.objects.filter(pk=queue_id).update(
        status=OfflineConversionQueue.Status.IMPORTED, imported_at=timezone.now()
    )


def mark_failed(*, queue_id: int, error: str) -> None:
    """Single UPDATE — F-expression bumps attempt_count without a fetch."""
    OfflineConversionQueue.objects.filter(pk=queue_id).update(
        status=OfflineConversionQueue.Status.FAILED, error_message=error[:1000], attempt_count=F("attempt_count") + 1
    )


def list_conversions(*, channel_idx: str | None = None, status: str | None = None) -> QuerySet[OfflineConversionQueue]:
    """Bounded QuerySet for the admin list view. Caller paginates.

    Validates ``status`` against the model's TextChoices so a typo in the query
    string produces 400 rather than a FieldError 500 with field-name leakage.
    """
    if status and status not in OfflineConversionQueue.Status.values:
        raise ValueError(f"Unknown status: {status!r}. Allowed: {sorted(OfflineConversionQueue.Status.values)}")
    qs = OfflineConversionQueue.objects.select_related(
        "lead", "lead__contact_form", "lead__contact_form__channel"
    ).order_by("-created_at")
    if channel_idx:
        qs = qs.filter(lead__contact_form__channel__idx=channel_idx)
    if status:
        qs = qs.filter(status=status)
    return qs


def get_conversion(*, pk: int) -> OfflineConversionQueue:
    return OfflineConversionQueue.objects.select_related(
        "lead", "lead__contact_form", "lead__contact_form__channel"
    ).get(pk=pk)


def reset_to_pending(*, queue_id: int, actor: str = "system") -> None:
    """Single UPDATE. Logs the actor for audit (admin retry endpoint passes the username)."""
    logger.info("OfflineConversionQueue %s reset to PENDING by %s", queue_id, actor)
    OfflineConversionQueue.objects.filter(pk=queue_id).update(
        status=OfflineConversionQueue.Status.PENDING, error_message="", imported_at=None
    )


def _get_active_config(lead: Lead) -> GoogleAdsConfig | None:
    """Resolve config for a lead's channel via FK columns only.

    One SQL join from GoogleAdsConfig → Channel → ContactForm using ``lead.contact_form_id``.
    Avoids the ``lead.contact_form.channel`` Python-attribute traversal that would fire
    extra SELECTs every time the signal handler runs (one per unprefetched FK hop).
    """
    config = (
        GoogleAdsConfig.objects.select_related("channel").filter(channel__contactform__id=lead.contact_form_id).first()
    )
    if config is None or not config.enabled or not config.customer_id:
        return None
    return config


def _spec_for_transition(config: GoogleAdsConfig, lead: Lead, new_status: str) -> _ConversionSpec | None:
    if new_status == Lead.Status.NEW and lead.source_type == Lead.SourceType.CALENDAR:
        return _ConversionSpec(config.meeting_booked_action_id, "Meeting Booked", config.meeting_booked_value)
    if new_status == Lead.Status.QUALIFIED:
        return _ConversionSpec(config.qualified_lead_action_id, "Qualified Lead", config.qualified_lead_value)
    if new_status == Lead.Status.WON:
        return _ConversionSpec(config.won_deal_action_id, "Won Deal", lead.deal_value or Decimal("0"))
    return None
