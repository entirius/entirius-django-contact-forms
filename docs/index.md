---
title: Contact Forms
description: Channel-scoped contact form submissions with file attachments and async email dispatch.
sidebar:
  label: Overview
  collapsed: true
---

`django-contact-forms` accepts arbitrary contact form submissions per channel, stores them with optional file attachments, and dispatches notification emails to the channel's admin address via Celery.

## What It Does

- Accepts POST submissions scoped to a Channel (validated by `X-API-KEY` header)
- Stores arbitrary JSON payload, email, slug, type, code, and language per submission
- Saves uploaded file attachments to private storage (outside `MEDIA_ROOT`)
- Queues notification emails via Celery (`contact_forms` queue); falls back to synchronous dispatch if queue is absent
- Enforces configurable limits on JSON body size, attachment count, and total attachment size

## Form Submission Flow

```
POST /api/contact/<version>/<channel_idx>/contact_form/
  → @channel_view resolves Channel by idx, validates X-API-KEY
    → ContactForm.objects.create() — stores email, slug, type, code, body
      → ContactFormAttachment.objects.create() — saves each uploaded file
        → send_contact_form_email.apply_async() — queues Celery task
          → renders HTML + TXT templates, attaches files, sends to channel.admin_email
```

If the `contact_forms` Celery queue does not exist, the email task runs synchronously and logs a warning.

## Key Concepts

### Channel

Scopes all data and controls where notification emails go. Each Channel has:

| Field | Description |
|---|---|
| `idx` | Unique string identifier used in URL path |
| `label` | Human-readable name (unique) |
| `default_language` | Fallback language if submission omits one |
| `admin_email` | Recipient for notification emails |

### APIKey

Authenticates requests. The `@channel_view` decorator reads `X-API-KEY` from the request header and checks it against `APIKey` records linked to the resolved channel. Missing or invalid keys return 401.

Generate keys with the management command — see [Configuration](./configuration/).

### ContactForm

Stores one form submission. Key fields:

| Field | Description |
|---|---|
| `id` | 12-digit random string PK (not an integer) |
| `email` | Submitter email (required) |
| `body` | Arbitrary JSON payload (enforces `FORMS_MAX_JSON_MB_SIZE`) |
| `slug` | Form identifier / page slug |
| `type` | Set from URL path when using the typed endpoint |
| `code` | Optional campaign or form code |
| `language` | Resolved language (falls back to channel default) |

### ContactFormAttachment

Stores uploaded files linked to a submission. Enforces two limits on `save()`:

- Total attachment size across all files for the form (`FORMS_MAX_ATTACHMENT_MB_SIZE`)
- Number of attachments per form (`FORMS_MAX_ATTACHMENT_COUNT`)

Files are stored at `PRIVATE_DIR/contact_form_attachments/{contact_form_id}/{timestamp}-{filename}` via `FileSystemStorage`, outside `MEDIA_ROOT`. Serving them requires a custom download view.

## Email Notification

The `send_contact_form_email` Celery task (queue: `contact_forms`):

1. Fetches the `ContactForm` and its attachments
2. Renders HTML and plain-text templates with submission context
3. Sends to `channel.admin_email` from `DEFAULT_FROM_EMAIL_CONTACT_FORM`
4. Attaches uploaded files inline

Override templates via `CONTACT_FORM_EMAIL_TEMPLATE_PATH_HTML` and `CONTACT_FORM_TEMPLATE_PATH_TXT` settings. Set `CONTACT_FORM_SEND_ADMIN_EMAIL = False` to disable dispatch entirely.

## What 2.1.0 Adds

Three opt-in features layered on top of the contact-form core:

- **Bookings** — public X-API-KEY endpoint that picks a slot, creates a Google Calendar event with a Meet link, and persists `ContactForm + Booking + Lead` in one transaction. See [Bookings](./bookings/).
- **Leads** — `Lead` model with status FSM (`new → contacted → qualified → won/lost`), attribution fields (gclid, hashed email, UTM, landing page), and an admin API for the sales pipeline. Plain submissions opt into Lead creation per `(channel, form_type, slug)` via a `LeadCreationRule` table managed in Grappelli — off by default. See [Leads](./leads/).
- **Google Ads offline conversions** — when a Lead transitions, an `OfflineConversionQueue` row is enqueued; a Celery worker drains the queue via the `google-ads-sdk` and flips `Lead.ads_conversion_imported`. Optional, gated by a global kill-switch. See [Ads Conversions](./ads-conversions/).

All three are off by default. Enable via the `ContactFormsSettings` singleton plus per-channel `BookingConfig` / `GoogleAdsConfig`. Modules that don't want bookings or Ads install plain `django-contact-forms`; the SDKs are pulled by the `[bookings]` and `[google-ads]` extras and lazy-imported so a missing extra never breaks Django startup.

## SDK packages

The 2.1.0 release introduces two pure-Python SDKs in the `python-modules/` tier:

- `python-modules/google-calendar-sdk` — wraps Google Calendar API v3 (service-account + domain-wide delegation). Used by the booking widget for free-busy queries and event creation.
- `python-modules/google-ads-sdk` — wraps the official `google-ads` client. Currently exposes `ConversionsClient.upload_click_conversions`; namespace is open for future `ReportingClient`, etc.

Both are framework-agnostic. They have no Django coupling and can be reused by other Volkanos modules (e.g. CRM) that want to talk to the same Google services.

## Related Modules

- **django-regional** — provides the `Language` model used for `Channel.default_language` and `ContactForm.language`
- **django-utils** — provides the `api_view`, `parse_form`, `require_http_method`, `BadRequest`, and `Response` decorators used by all views

## Pages

- [Bookings](./bookings/) — public booking endpoint, calendar provider plug-in, slot rules
- [Leads](./leads/) — Lead data model, status FSM, admin API
- [Ads Conversions](./ads-conversions/) — opt-in Google Ads upload chain, OAuth setup, troubleshooting
- [Configuration](./configuration/) — settings, API key generation, channel setup, Celery queues
- [Log Codes](./log-codes/) — error and warning codes logged by views and the email task
- [Changelog](./changelog/) — release history
- [Database Diagrams](./erd/) — auto-generated ER diagrams
