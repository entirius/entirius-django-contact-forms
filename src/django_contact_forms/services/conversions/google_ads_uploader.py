# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Drains the OfflineConversionQueue for one channel by calling the google-ads-sdk."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from django.db.models import QuerySet
from django.utils import timezone

from django_contact_forms import settings as cf_settings
from django_contact_forms.models import GoogleAdsConfig, Lead, OfflineConversionQueue

BATCH_SIZE_DEFAULT = 100


@dataclass(frozen=True)
class UploadOutcome:
    imported: int
    failed: int
    skipped: int


def upload_pending(*, channel_idx: str, batch_size: int | None = None) -> UploadOutcome:
    """Upload up to batch_size PENDING rows for the given channel. Lazy-imports the SDK."""
    config = _get_config(channel_idx)
    if config is None:
        return UploadOutcome(0, 0, 0)

    pending: QuerySet[OfflineConversionQueue] = (
        OfflineConversionQueue.objects.select_related("lead", "lead__contact_form", "lead__contact_form__channel")
        .filter(status=OfflineConversionQueue.Status.PENDING, lead__contact_form__channel=config.channel)
        .order_by("created_at")[: batch_size or _batch_size()]
    )
    rows = list(pending)
    if not rows:
        return UploadOutcome(0, 0, 0)

    client = _build_client(config)
    sdk_conversions = [_to_sdk_conversion(row, config) for row in rows]
    result = client.upload_click_conversions(sdk_conversions, partial_failure=True)

    return _persist_outcome(rows, result)


def _build_client(config: GoogleAdsConfig) -> Any:
    """Lazy import — service can be imported without google-ads-sdk installed."""
    from google_ads_sdk import ConversionsClient

    return ConversionsClient(
        developer_token=cf_settings.GOOGLE_ADS_DEVELOPER_TOKEN,
        oauth_client_id=cf_settings.GOOGLE_ADS_OAUTH_CLIENT_ID,
        oauth_client_secret=cf_settings.GOOGLE_ADS_OAUTH_CLIENT_SECRET,
        refresh_token=config.oauth_refresh_token,
        customer_id=config.customer_id,
        login_customer_id=config.login_customer_id or None,
    )


def _to_sdk_conversion(row: OfflineConversionQueue, config: GoogleAdsConfig) -> Any:
    from google_ads_sdk import ClickConversion

    return ClickConversion(
        conversion_action_id=row.conversion_action_id,
        conversion_date_time=_format_datetime(row.conversion_time),
        conversion_value=float(row.conversion_value),
        currency_code=row.currency_code or config.default_currency_code,
        gclid=row.gclid or None,
        hashed_email=row.hashed_email or None,
    )


def _persist_outcome(rows: list[OfflineConversionQueue], result: Any) -> UploadOutcome:
    """Two bulk_update calls (one per terminal state) instead of N per-row .save()s."""
    failed_indices = {f.index for f in result.failures}
    failure_messages = {f.index: f.error_message for f in result.failures}
    now = timezone.now()

    to_import: list[OfflineConversionQueue] = []
    to_fail: list[OfflineConversionQueue] = []

    for idx, row in enumerate(rows):
        if idx in failed_indices:
            row.status = OfflineConversionQueue.Status.FAILED
            row.error_message = failure_messages.get(idx, "")[:1000]
            row.attempt_count = (row.attempt_count or 0) + 1
            to_fail.append(row)
        else:
            row.status = OfflineConversionQueue.Status.IMPORTED
            row.imported_at = now
            to_import.append(row)

    if to_fail:
        OfflineConversionQueue.objects.bulk_update(to_fail, ["status", "error_message", "attempt_count", "modified_at"])
    if to_import:
        OfflineConversionQueue.objects.bulk_update(to_import, ["status", "imported_at", "modified_at"])
        Lead.objects.filter(id__in=[r.lead_id for r in to_import]).update(
            ads_conversion_imported=True, ads_imported_at=now
        )

    return UploadOutcome(imported=len(to_import), failed=len(to_fail), skipped=0)


def _get_config(channel_idx: str) -> GoogleAdsConfig | None:
    config = GoogleAdsConfig.objects.select_related("channel").filter(channel__idx=channel_idx).first()
    if config is None or not config.enabled or not config.customer_id or not config.oauth_refresh_token:
        return None
    return config


def _batch_size() -> int:
    return cf_settings.CONTACT_FORMS_CONVERSIONS_BATCH_SIZE


def _format_datetime(dt: datetime) -> str:
    """Google Ads expects 'YYYY-MM-DD HH:MM:SS+HH:MM'.

    Refuses naive datetimes — those would silently produce an invalid string
    that the SDK then rejects with a confusing error.
    """
    if dt.tzinfo is None:
        raise ValueError(f"_format_datetime requires a tz-aware datetime, got naive: {dt!r}")
    # isoformat → '2026-04-19T10:00:00+00:00' → swap T for space, keep colon-offset.
    return dt.isoformat(sep=" ", timespec="seconds")
