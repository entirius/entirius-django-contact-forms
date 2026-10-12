---
title: Ads Conversions
description: Optional Google Ads offline conversion upload — Lead status changes drain through a Celery worker via google-ads-sdk.
sidebar:
  label: Ads Conversions
---

This is the optional half of the 2.1.0 release. When a Lead transitions, an `OfflineConversionQueue` row is enqueued; a Celery worker drains the queue every five minutes and reports back to Google Ads. If you don't want this, just leave it off — none of the SDK code is loaded.

## When the queue gets a row

`queue_service.enqueue_for_lead` runs inside the `lead_status_changed` signal receiver. It maps `(old_status, new_status)` to a conversion action:

| Old → New | Condition | Action ID source | Value source |
|---|---|---|---|
| `* → new` | only if `source_type == "calendar"` | `GoogleAdsConfig.meeting_booked_action_id` | `meeting_booked_value` (default 200) |
| `* → qualified` | always | `qualified_lead_action_id` | `qualified_lead_value` (default 500) |
| `* → won` | always | `won_deal_action_id` | `Lead.deal_value` (or 0) |
| anything else | — | — | nothing enqueued |

The receiver returns silently when:

- Singleton `ContactFormsSettings.google_ads_enabled = False`
- Channel has no `GoogleAdsConfig` or it's `enabled = False`
- The relevant action ID is empty string
- A row for `(lead, action_id)` already exists (UniqueConstraint dedupes via `get_or_create`)

The new row's `status`:

- `PENDING` if the Lead has a `gclid` or `hashed_email` (something Google Ads can match against)
- `SKIPPED` if neither — Google Ads has no way to attribute the conversion

`gclid` and `hashed_email` on the row are frozen at enqueue time, so editing the Lead later doesn't affect what gets uploaded.

## Enable it

Three switches:

1. Singleton `ContactFormsSettings.google_ads_enabled = True`.
2. Per-channel `GoogleAdsConfig.enabled = True`, with `customer_id` and `oauth_refresh_token` filled in.
3. Three deployment-wide secrets in Django settings: `GOOGLE_ADS_DEVELOPER_TOKEN`, `GOOGLE_ADS_OAUTH_CLIENT_ID`, `GOOGLE_ADS_OAUTH_CLIENT_SECRET`.

The `[google-ads]` extra must be installed for the Celery worker — services that don't need this feature pin plain `django-contact-forms` and the SDK isn't even imported.

## OAuth refresh token

The SDK doesn't run an interactive OAuth flow. Get a refresh token once via a small admin script (e.g. `google-auth-oauthlib`) then paste it into `GoogleAdsConfig.oauth_refresh_token`. The field is an `EncryptedTextField` — Fernet-encrypted at rest with a key derived from Django `SECRET_KEY`. Back up your `SECRET_KEY` safely; losing it means losing the ability to decrypt stored tokens.

## Worker

```python
@shared_task(queue="contact_forms_conversions", bind=True, max_retries=3, default_retry_delay=300)
def upload_pending_conversions(self, channel_idx: str) -> dict: ...
```

Lazy-imports `ConversionsClient` from `google-ads-sdk` so the task module loads without the `[google-ads]` extra. Schedule it in the consuming service's Celery Beat config:

```python
"contact-forms-upload-conversions": {
    "task": "django_contact_forms.tasks.upload_pending_conversions.upload_pending_conversions",
    "schedule": crontab(minute="*/5"),
    "options": {"queue": "contact_forms_conversions"},
}
```

The dispatcher loops over channels with `GoogleAdsConfig.enabled=True` and pending rows, dispatching one task per channel. The worker reads up to `CONTACT_FORMS_CONVERSIONS_BATCH_SIZE` (default 100) rows per call and uploads them with `partial_failure=True`.

For each accepted row: `status = IMPORTED`, `imported_at = now`, `Lead.ads_conversion_imported = True` via a single bulk update. For each rejected row: `status = FAILED`, `error_message = first 1000 chars`, `attempt_count++`.

## Admin API

```
GET   /api/contact-forms/v2/admin/offline-conversions/?channel=&status=
GET   /api/contact-forms/v2/admin/offline-conversions/{pk}/
POST  /api/contact-forms/v2/admin/offline-conversions/{pk}/retry/   # resets to PENDING
```

The admin page has a bulk action with the same effect — useful after fixing a config error (wrong customer_id, expired refresh token).

## Pull-pattern compatibility

The original ecom-adsware tool used a pull pattern: an external Google Apps Script polled `/pending` and posted results to `/mark-imported`. The Volkanos module deliberately does NOT expose those endpoints — the push pattern via Celery is simpler operationally and keeps the code path observable. If a deployment needs the pull pattern (e.g. firewall constraints on the Django container), it can be added as a separate feature later; nothing in the data model would change.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| Queue stays empty after Lead transition | `google_ads_enabled` off, `GoogleAdsConfig.enabled` off, or action ID empty for that status |
| Rows go straight to `SKIPPED` | Lead has no gclid AND no hashed_email — Google Ads can't match. Capture gclid on the form. |
| Rows go to `FAILED` with "GCLID expired" | Click is older than 90 days (Google Ads matching window) |
| Rows go to `FAILED` with auth error | Refresh token rejected — re-do the OAuth flow and paste a fresh token |
| Worker never runs | Beat schedule missing OR queue `contact_forms_conversions` not bound to a worker |
| `ImportError: google_ads_sdk` | `[google-ads]` extra not installed in the worker image — `pip install -e ".[google-ads]"` |
