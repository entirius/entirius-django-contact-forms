---
title: Form Types & Client Copy
description: Per-channel form-type catalog, how submit resolves a type, and how the submitter receives a copy of their message.
---

Since 2.2.0 a form submission carries a **type** drawn from a per-channel catalog, and the submitter can receive a **copy** of their message. Both are driven from the database, not hardcoded in the storefront or CMS.

## Form types

`FormType` is the per-channel catalog of allowed types. Seed it via fixtures — the reference set is `general`, `product`, `default` (one row flagged `is_default` per channel).

| Field | Meaning |
|---|---|
| `code` | The value stored on `ContactForm.type` (unique per channel) |
| `label` | Human-readable name for the CMS/storefront selector |
| `is_default` | Used when a submission has no type or an unknown one (one per channel) |

List a channel's types instead of hardcoding them:

- Storefront: `GET /api/contact-forms/v2/{channel_idx}/form-types/` (X-API-KEY, throttled)
- CMS: `GET /api/contact-forms/v2/admin/form-types/?channel_idx={idx}` (JWT + admin)

### How submit resolves the type

The type is taken from the first of these that is present, then normalized against the channel catalog:

1. `form_type` request field
2. `body.form_type`
3. legacy `body.type`
4. URL segment `type_id` (`/submit/<type_id>/`)

If the resolved value is empty or not in the channel's catalog, it falls back to the channel's `is_default` row, then to the `CONTACT_FORM_DEFAULT_TYPE` setting. Resolution never rejects a submission — unknown types are logged and coerced to the default.

Existing submissions are **not** backfilled; rows created before 2.2.0 keep their original (usually empty) `type`.

## Client copy

By default only the admin is notified. To also send the submitter a copy:

1. Set `send_client_copy=true` on the matching `FormNotificationConfig` (same `exact → type-level → channel-level → global` fallback as the admin toggle).
2. Have the submission opt in with `body.send_copy=true`.

Both must be true, and the submission must carry an email. The copy is a distinct email — rendered by django-email's `ContactFormClientCopyEmail` with its own subject and template ("thank you for contacting us"), in the submitter's language — not a CC of the admin notification.

```json
POST /api/contact-forms/v2/{channel_idx}/submit/
{
  "email": "visitor@example.com",
  "form_type": "product",
  "body": { "message": "Do you ship to Norway?", "send_copy": true }
}
```

The admin notification and the client copy are dispatched by the same Celery task (`contact_forms` queue); the task sends each independently, so one failing does not block the other.
