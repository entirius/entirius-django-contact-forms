---
title: API
description: Admin and public v2 endpoints and the legacy v1 endpoints of django-contact-forms.
---

## API v2 Endpoints

### Admin (JWT + IsAdminUser)

URL prefix: `api/contact-forms/v2/admin/`

```
GET   submissions/                              List (paginated, filterable)
GET   submissions/<str:pk>/                     Retrieve (with body + attachments)
GET   submissions/<pk>/attachments/<id>/download/   Download file
GET   form-types/?channel_idx=<idx>             List a channel's form types (CMS selector source)
GET   notifications/                            List notification configs
POST  notifications/                            Create config
GET   notifications/<int:pk>/                   Retrieve config
PATCH notifications/<int:pk>/                   Update config
DELETE notifications/<int:pk>/                  Delete config
```

Filters on submissions: `type`, `slug`, `channel` (query params), `search` (id/email/code).
Ordering: `created_at`, `-created_at`, `email`, `-email`, `type`, `-type`.

### Public (X-API-KEY)

URL prefix: `api/contact-forms/v2/`

```
GET   <channel_idx>/form-types/                List the channel's form types (throttled)
POST  <channel_idx>/submit/                    Submit form
POST  <channel_idx>/submit/<type_id>/          Submit form with explicit type (legacy URL)
```

Supports multipart/form-data for file uploads. Body can be JSON object or string.

**Form type** comes from (priority): the `form_type` request field → `body.form_type`
→ legacy `body.type` → URL `type_id`. The value is normalized against the channel's
`FormType` catalog; empty/unknown resolves to the channel default. **Client copy:** set
`body.send_copy=true` and a matching `FormNotificationConfig.send_client_copy=true` to
have the submitter receive a confirmation copy. Submit is rate-limited
(scope `contact_forms_submit`).

## API v1 Endpoints (Legacy)

URL prefix: `api/contact/<version>/<channel_idx>/`

```
POST  contact_form/             Submit (no type)
POST  contact_form/<type_id>/   Submit with type
```

**Auth:** `X-API-KEY` via `@channel_view` decorator. Marshmallow DTOs. Unchanged.
