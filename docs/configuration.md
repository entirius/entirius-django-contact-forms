---
title: Configuration
description: Settings, API key generation, channel setup, and Celery queue configuration for django-contact-forms.
---

## Settings

All settings are read from Django settings with the defaults shown. Only `PRIVATE_DIR` is required — the module raises `EnvironmentError` at import time if it is not set.

| Setting | Type | Default | Description |
|---|---|---|---|
| `PRIVATE_DIR` | `str` | **required** | Root directory for private file storage. Raises `EnvironmentError` if unset. |
| `FORMS_MAX_JSON_MB_SIZE` | `int` | `50` | Maximum size of `ContactForm.body` JSON in MB. Enforced on `save()`. |
| `FORMS_MAX_ATTACHMENT_MB_SIZE` | `int` | `50` | Maximum total size of all attachments per submission in MB. |
| `FORMS_MAX_ATTACHMENT_COUNT` | `int` | `10` | Maximum number of file attachments per submission. |
| `DEFAULT_FROM_EMAIL_CONTACT_FORM` | `str \| None` | `None` | From address for outbound notification emails. Falls back to Django's `DEFAULT_FROM_EMAIL` if `None`. |
| `CONTACT_FORM_SEND_ADMIN_EMAIL` | `bool` | `True` | Global fallback for the admin notification when no `FormNotificationConfig` matches. |
| `CONTACT_FORM_SEND_CLIENT_COPY` | `bool` | `False` | Global fallback for the copy-to-submitter when no config matches. Per-config `send_client_copy` overrides it. |
| `CONTACT_FORM_DEFAULT_TYPE` | `str` | `"default"` | Type code used when a submission has no/unknown type and the channel has no `is_default` `FormType`. |

### 2.1.0 — Google Ads (only when `[google-ads]` extra installed)

| Setting | Type | Default | Description |
|---|---|---|---|
| `GOOGLE_ADS_DEVELOPER_TOKEN` | `str` | `""` | Developer token from the Google Ads API console. |
| `GOOGLE_ADS_OAUTH_CLIENT_ID` | `str` | `""` | OAuth2 client ID. |
| `GOOGLE_ADS_OAUTH_CLIENT_SECRET` | `str` | `""` | OAuth2 client secret. |
| `CONTACT_FORMS_CONVERSIONS_BATCH_SIZE` | `int` | `100` | Max OfflineConversionQueue rows the worker drains per call. |

Per-channel `customer_id`, `login_customer_id`, conversion-action IDs, and the encrypted `oauth_refresh_token` live on `GoogleAdsConfig` rows (DB, runtime-changeable). Per-deployment secrets stay in Django settings (require redeploy to rotate).

The bundled templates are at `django_contact_forms/email/contact_form_email.{html,txt}` inside the package. Override them by pointing the settings to your own template paths (resolved via Django's template loaders).

## 2.1.0 — Singleton Kill-Switches

`ContactFormsSettings` is a single-row model managed via Django admin (`Contact Forms → Contact Forms settings`). Both default to `False`:

| Toggle | Effect when off | Effect when on |
|---|---|---|
| `bookings_enabled` | All booking endpoints return `400 BOOKING_DISABLED` | Booking flow runs as long as the channel `BookingConfig.enabled` is also true |
| `google_ads_enabled` | `lead_status_changed` receiver no-ops | Lead status changes enqueue `OfflineConversionQueue` rows (subject to `GoogleAdsConfig.enabled` per channel) |

Helper functions cache the values for 60s: `is_bookings_enabled()`, `is_google_ads_enabled()`. Cache invalidates automatically on `ContactFormsSettings.save()`.

## 2.1.0 — Per-Channel Config

Two new sub-resources of Channel (Django admin: `Contact Forms → Booking configs` / `Google Ads configs`):

**BookingConfig** — service-account credentials path, impersonate email, `calendar_id`, slot rules (`start_hour`, `end_hour`, `slot_duration_minutes`, `weekdays_only`, `days_ahead`, `timezone`), and the `event_summary_template` (use `{name}` as a placeholder). See [Bookings](../bookings/) for the full Google Calendar setup procedure.

**GoogleAdsConfig** — `customer_id`, optional `login_customer_id` (MCC), encrypted `oauth_refresh_token`, default currency, and three conversion-action ID slots (`meeting_booked_action_id`, `qualified_lead_action_id`, `won_deal_action_id`) with their default values. See [Ads Conversions](../ads-conversions/) for the OAuth setup.

## 2.1.0 — Celery Queues

| Queue | Task | Cadence |
|---|---|---|
| `contact_forms` | `send_contact_form_email` (existing) | On submission |
| `contact_forms_conversions` | `upload_pending_conversions` (new) | Beat every 5 min, one task per channel with pending rows |

## API Key Generation

Create an `APIKey` record and write it to disk:

```bash
# Default path: DATA_DIR/tmp/api-key/key
python manage.py forms-generate-api-key

# Custom path
python manage.py forms-generate-api-key --file_path /path/to/key
```

The command prints the SHA256 key to stdout and writes it to the file. The generated key has no channel assigned (`channel=NULL`). After generation, link it to a channel via the Django admin (`Contact Forms → API Keys → assign channel`).

With `entirius-django-access` installed, widget keys are access tokens: `forms-generate-api-key` refuses and names
`manage.py access_token create --scope contact_forms.submit --channel <idx> --application <name>` (booking keys:
`--scope contact_forms.booking`), the `APIKey` table is never read and its admin is read-only. Existing keys keep
working as imported legacy tokens (`access_import_legacy_keys`). The admin shows only the last four characters of a key
on both paths.

Without `django_access` (legacy path) the admin "Add" form still exists but cannot show the generated key (the admin
never displays raw keys): create legacy keys with `forms-generate-api-key` only.

## Throttles

Public v2 routes and the v1 `contact_form/` routes (which share the `contact_forms_submit` buckets) are throttled; rates come from `REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]`, with a class fallback
when a scope is missing or malformed. No cache key holds key material.

| Scope | Fallback | Bucket |
|---|---|---|
| `contact_forms_submit` | 30/hour | without access: per key (SHA-256 prefix); with access: per token + client address |
| `contact_forms_form_types` | 120/hour | as above |
| `contact_forms_booking` | 10/hour | without access: per client address; with access: per token + client address |
| `contact_forms_submit_token` | 20 × the submit fallback (600/hour) | with access only: per token, every address together |
| `contact_forms_form_types_token` | 20 × the form-types fallback (2400/hour) | as above |
| `contact_forms_booking_token` | 20 × the booking fallback (200/hour) | as above |

The ceiling derives from the class fallback, not from a configured visitor rate: raise the `_token` scope when you raise the visitor rate. It counts only requests the per-visitor bucket let through; the visitor bucket in turn records its hit before the ceiling is consulted. The client address is DRF's
`get_ident`, which trusts `X-Forwarded-For` unless the service sets `NUM_PROXIES`.

## Channel Setup

Create and configure channels in the Django admin at `Contact Forms → Channels`:

| Field | Description |
|---|---|
| `idx` | URL-safe unique identifier — used in the API path. Validated by `idx-normalizator`. |
| `label` | Human-readable name (unique). |
| `default_language` | Fallback language if a submission omits the `language` field. |
| `admin_email` | Email address that receives notification emails for this channel. |

Each channel needs at least one `APIKey` linked to it before accepting submissions.

## Celery Queue

Route contact form emails to a dedicated queue:

```python
# settings.py
CELERY_TASK_ROUTES = {
    "django_contact_forms.*": {"queue": "contact_forms"},
}
```

The `contact_forms` queue must exist in the broker before the service starts. If it is absent, email dispatch falls back to synchronous execution and logs a warning. Start a worker that consumes this queue:

```bash
celery -A your_project worker -Q contact_forms --loglevel=info
```

## File Storage

Attachments are stored outside `MEDIA_ROOT` using `FileSystemStorage`:

```
PRIVATE_DIR/
└── contact_form_attachments/
    └── {contact_form_id}/
        └── {timestamp}-{original_filename}
```

Set `PRIVATE_DIR` in Django settings before starting the application. The directory is created automatically on first write. Files stored here are not served by Django's static file machinery — implement a custom download view with appropriate access control if submissions need to be retrieved.
