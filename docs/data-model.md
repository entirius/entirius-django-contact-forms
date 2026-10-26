---
title: Data Model
description: Entities of django-contact-forms and how they relate.
---

```
Channel (idx↑, label↑, admin_email, default_language FK→Language)
    ├── ContactForm (id[12-digit str PK], email, slug, type, code, body{JSON}, language FK)
    │    └── ContactFormAttachment (name, attachment[FileField], FK→ContactForm)
    ├── APIKey (key[SHA256], FK→Channel)
    ├── FormType (code, label, is_default, FK→Channel)
    │    UniqueConstraint(channel, code) + one is_default per channel
    ├── FormNotificationConfig (form_type, slug, send_email, send_client_copy, recipient_email)
    │    UniqueConstraint(channel, form_type, slug)
    ├── BookingConfig (calendar backend, FOMO fields) ── BookingTimeWindow (order, start/end_time)
    ├── LeadCreationRule (channel/type/slug → create Lead)
    └── GoogleAdsConfig (OneToOne, encrypted refresh token)
ContactForm ── Lead (status pipeline) ── OfflineConversionQueue (conversion upload rows)
```

- `ContactForm.id` is a randomly generated 12-digit **string** PK — never auto-increment
- `FormType` is the per-channel catalog of allowed types (seeded via fixtures, e.g.
  general/product/default). Submit resolves an incoming type against it; empty/unknown
  falls back to the channel's `is_default` row, then `CONTACT_FORM_DEFAULT_TYPE`.
- `FormNotificationConfig` controls per-type/slug email behavior with fallback chain:
  exact(channel,type,slug) → type-level(channel,type,"") → channel-level(channel,"","") → global setting.
  `send_email` gates the admin notification; `send_client_copy` gates the submitter copy
  (additionally requires `body.send_copy` truthy on the submission).

Diagrams: [Database Diagrams](erd.md).
