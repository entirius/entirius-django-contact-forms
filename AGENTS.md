# AGENTS.md

Channel-scoped contact form submissions with file attachments, per-type email notification config,
booking calendar with optional Google Calendar backend, lead tracking with Google Ads offline-conversion
uploads, and async email dispatch for the Volkanos ecommerce platform — distribution
`entirius-django-contact-forms`, Django app `django_contact_forms`.
Dual API surface: v1 (legacy function-based) + v2 (DRF ViewSets, Pydantic, drf-spectacular).

**Tech:** Python >=3.11, Django >=4.0, DRF, Pydantic 2, drf-spectacular, Celery
(`contact_forms` + `contact_forms_conversions` queues)

## Commands

| Command | Meaning |
|---|---|
| `make install` | sync dependencies (uv, incl. extras) |
| `make check` | lint + format-check (ruff) |
| `make fix` | auto-fix lint + format |
| `make test` | test suite (pytest) |
| `make test-legacy` | test suite without django_access (legacy key path) |

## Conventions

- English only: code, docs, commits, branches, PRs.
- MPL-2.0: every non-trivial source file carries the license header (pre-commit inserts it).
- Toolchain: uv + ruff + hatchling + pytest; all config in `pyproject.toml`; `uv.lock` committed.
- Git flow: `master` (production) + `develop` (integration); changes land via PR; semver tag on `master`.
- Never rename the Django app `django_contact_forms` — app_label and DB table prefix are a public schema contract.
- Default: do not commit — git is the user's call.

## Commit Message Format

**NEVER add `Co-Authored-By: Claude ...` (or any other Claude/Anthropic attribution) to commit messages.**

This overrides the default Claude Code behavior of appending a `Co-Authored-By` trailer. Commit messages MUST contain only the user's authored content — no robot footer, no "Generated with Claude Code" line, no co-author trailer.

Same rule applies to PR descriptions: no `Generated with [Claude Code]` footer.

## Architecture

```
src/django_contact_forms/
├── models/
│   ├── base_model.py                   # BaseModel (created_at, modified_at)
│   ├── channel.py                      # Channel (idx, label, admin_email, default_language)
│   ├── contact_form.py                 # ContactForm (12-digit string PK, JSON body, language FK)
│   ├── contact_form_attachment.py      # ContactFormAttachment (FileField in PRIVATE_DIR)
│   ├── contact_forms_settings.py       # ContactFormsSettings (bookings/google-ads feature toggles)
│   ├── api_key.py                      # APIKey (SHA256, FK→Channel)
│   ├── form_type.py                    # FormType (per-channel type catalog, is_default)
│   ├── form_notification_config.py     # FormNotificationConfig (per type/slug email + client copy)
│   ├── booking_config.py               # BookingConfig (per-channel calendar + FOMO settings)
│   ├── booking_time_window.py          # BookingTimeWindow (≥1 working windows per config)
│   ├── booking.py                      # Booking (slot reservations)
│   ├── lead.py                         # Lead (FK→ContactForm, status pipeline)
│   ├── lead_creation_rule.py           # LeadCreationRule (per channel/type/slug routing)
│   ├── google_ads_config.py            # GoogleAdsConfig (OneToOne→Channel, encrypted refresh token)
│   ├── offline_conversion.py           # OfflineConversionQueue (FK→Lead)
│   └── managers/
│
├── schemas/                            # Pydantic requests/responses (v2)
├── services/
│   ├── contact_form_service.py         # list, get, create submissions + get attachments
│   ├── notification_service.py         # should_send_email (fallback chain), dispatch_email
│   ├── booking_service.py              # slot grid, availability, create booking
│   ├── booking_admin_service.py        # admin CRUD for booking configs
│   ├── booking_notification_service.py # booking e-mails (soft django-email import)
│   ├── lead_service.py                 # lead lifecycle, status transitions
│   ├── lead_creation_rule_service.py   # rule resolution on submit
│   ├── channel_integrations_service.py # per-channel integration status
│   ├── calendar/                       # backend factory: google_calendar (lazy SDK) / local_only
│   └── conversions/                    # Google Ads uploader (lazy SDK), queue handling
│
├── api/
│   ├── admin/                          # v2 Admin API (JWT + IsAdminUser)
│   └── public/                         # v2 Public API (X-API-KEY auth)
│
├── views/views.py                      # v1 legacy: create_contact_form (unchanged)
├── tasks/
│   ├── send_contact_form_email.py      # @shared_task(queue="contact_forms")
│   └── upload_pending_conversions.py   # @shared_task(queue="contact_forms_conversions")
│
├── utils/                              # decorators (v1 auth), payloads (marshmallow, v1),
│                                       # encrypted_field, v2_errors, workers
├── management/commands/                # forms-generate-api-key (refuses when django-access is installed)
├── admin/                              # Django admin registrations
├── fixtures/                           # Seed data (channels, API keys, configs, samples)
├── templates/django_contact_forms/email/
├── apps.py / settings.py / urls.py     # v1 + v2 admin + v2 public URL includes
```

Layer rule: `API → Services → Models → DB`. No business logic in views.

## Data Model

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

## Notification Config

`FormNotificationConfig` controls whether email is sent and to whom for each form submission.

**Fallback chain** (one walk, shared by `should_send_email` and `should_send_client_copy`):
1. Exact match: `(channel, form_type, slug)`
2. Type-level: `(channel, form_type, "")`
3. Channel-level: `(channel, "", "")`
4. Global: `CONTACT_FORM_SEND_ADMIN_EMAIL` / `CONTACT_FORM_SEND_CLIENT_COPY` setting

`recipient_email` override: if set on the matching config, overrides `channel.admin_email`.

**Client copy:** `send_client_copy` on the matching config, AND `body.send_copy` truthy on
the submission, AND a non-empty submitter email → the submitter receives a copy rendered by
django-email's `ContactFormClientCopyEmail` (separate template/subject from the admin one).

**Editable fields** via `update_config`: `form_type`, `slug`, `send_email`,
`send_client_copy`, `recipient_email` (whitelisted — anything else raises `ValueError`).

## Multilang Emails

All templates, translations, and rendering live in **django-email** (`email` extra). This
module stores the `ContactForm.language` FK and resolves it to an ISO2
code; the actual render happens inside `django-email EmailService`
subclasses.

| Email | Language source | Subclass |
|---|---|---|
| Booker confirmation | `ContactForm.language` → `channel.default_language` | `BookingConfirmationEmail` |
| Booking admin notification | `channel.default_language` | `BookingAdminNotificationEmail` |
| Generic form notification | `channel.default_language` | `ContactFormSubmissionEmail` |
| Client copy (to submitter) | `ContactForm.language` → `channel.default_language` | `ContactFormClientCopyEmail` |

Full pattern + "how to add a new translated email": [docs/multilang-emails.md](docs/multilang-emails.md).

## Multi-window working hours

Working hours per channel are defined as ≥1 ``BookingTimeWindow`` rows linked to
``BookingConfig`` (FK with ``related_name="time_windows"``). Each window has
``order``, ``start_time``, ``end_time`` (both ``TimeField`` — minute precision).
Slot generation iterates each window independently; clusters and synthetic FOMO
busy periods are constrained per-window (never span boundaries).
Admin edits windows via the inline editor on ``BookingConfigAdmin``
(e.g., 10:00-12:30 + 16:00-17:00).

API ``Slot`` shape unchanged — public ``/bookings/slots/`` endpoint emits a flat
list per day; multi-window structure lives only in the config layer.

## FOMO synthetic busy slots

Cosmetic layer that adds fake busy slots on top of real Google Calendar busy
intervals so a young or low-traffic booking calendar doesn't look empty (which
itself deters visitors). Three layers in
[`services/calendar/fomo.py`](src/django_contact_forms/services/calendar/fomo.py):

1. **Time-decay** — today ×1.5 intensity, tomorrow ×1.3, days 2-6 ×1.0,
   days 7+ ×0.75. Capped at 80% of slots blocked per day.
2. **Slot clusters** — 2-4 consecutive synthetic-busy slots per cluster, weighted
   toward business peak hours (10-12, 13-16). Mirrors how real bookings cluster.
3. **Day blackouts** — 0-3 full-day blocks within the visible window. Today and
   tomorrow are always excluded so "fresh availability" urgency works.

Per-day RNG seed = `HMAC-SHA256(SECRET_KEY, channel.idx + day.isoformat())` so the
layout is stable across page refreshes within a calendar day and rotates
naturally at midnight. The HMAC construction (rather than a raw `sha256(...)`
concatenation) is what gives us the SECRET_KEY-keyed determinism; without it,
anyone scraping `channel.idx` could replay the layout.

**Three `BookingConfig` fields** (Django admin only — no CMS panel):

| Field | Default | Range |
|---|---|---|
| `fomo_enabled` | `False` | bool |
| `fomo_intensity` | `50` | 0-100 (0=off, 50=balanced, 80=aggressive) |
| `fomo_blackout_full_days` | `1` | 0-3 |

**Integration**: `booking_service.get_available_slots` merges synthetic into the
real busy list before slot grid generation. `is_slot_free` (race-condition guard
before `create_event`) consults only the real backend — synthetic intervals
**never** block an actual booking, only filter visibility. The API response shape
is unchanged (`available: bool`); no synthetic flag leaks to clients.

Disable per-channel by toggling `fomo_enabled=False`. Disable globally by setting
`fomo_intensity=0` for every config (or leaving the master toggle off).

## Celery Tasks

**`send_contact_form_email`** — Queue: `contact_forms`. Thin async wrapper
around django-email service classes. `send_admin` (default True) sends the
admin notification via `ContactFormSubmissionEmail`; `send_client_copy`
(default False) additionally sends the submitter copy via
`ContactFormClientCopyEmail`. Controlled by `notification_service` in v2, by
`CONTACT_FORM_SEND_ADMIN_EMAIL` in v1. Deprecated kwargs
(`template_html_path`, `subject`, `extra_context`) remain in the signature
for backward compatibility with previously enqueued tasks but are ignored.

**`upload_pending_conversions`** — Queue: `contact_forms_conversions`. Batch-uploads
queued `OfflineConversionQueue` rows via the `google-ads` extra (lazy import);
retries with backoff (`max_retries=3`).

## Settings Reference

| Setting | Default | Description |
|---------|---------|-------------|
| `PRIVATE_DIR` | **required** | Root for private file storage |
| `FORMS_MAX_JSON_MB_SIZE` | `50` | Max JSON body size in MB |
| `FORMS_MAX_ATTACHMENT_MB_SIZE` | `50` | Max total attachment size per form |
| `FORMS_MAX_ATTACHMENT_COUNT` | `10` | Max attachments per form |
| `DEFAULT_FROM_EMAIL_CONTACT_FORM` | `None` | From address for emails |
| `CONTACT_FORM_SEND_ADMIN_EMAIL` | `True` | Global admin-email toggle (v1 + v2 fallback) |
| `CONTACT_FORM_SEND_CLIENT_COPY` | `False` | Global client-copy fallback (per-config overrides) |
| `CONTACT_FORM_DEFAULT_TYPE` | `"default"` | Type code used when no FormType matches / is_default |
| `GOOGLE_ADS_DEVELOPER_TOKEN` | `""` | Google Ads global developer token (`google-ads` extra) |
| `GOOGLE_ADS_OAUTH_CLIENT_ID` / `_SECRET` | `""` | OAuth app credentials (`google-ads` extra) |
| `CONTACT_FORMS_CONVERSIONS_BATCH_SIZE` | `100` | Conversion upload batch size |
| `CONTACT_FORMS_CREDENTIALS_DIR` | `"/app/credentials/"` | Service-account JSON dir (`bookings` extra) |

## Testing

```bash
uv run pytest              # postgres via DATABASE_URL (default: postgres:postgres@localhost:5432/test)
```

| File | Scope |
|------|-------|
| `test_admin_api.py` | Auth (401/403/200), list, retrieve, search, pagination, notification config CRUD |
| `test_public_api.py` | Auth (401 no key / wrong key, 201 valid), submit, validation, multipart upload |
| `test_services.py` | contact_form_service CRUD, notification_service fallback chain |
| `test_service_booking.py` / `test_booking_time_window.py` / `test_fomo.py` | booking domain |
| `test_service_lead.py` / `test_service_conversions.py` | leads + conversion uploads |
| `test_form_types.py` / `test_multilang_booking.py` / `test_calendar_backends.py` | type catalog, i18n, backends |

## Dependencies

**Runtime:** Django >=4.0, celery, DRF >=3.14, djangorestframework-simplejwt >=5.3, pydantic >=2.0,
drf-spectacular >=0.27, cryptography, marshmallow (v1 only), django-admin-inline-paginator

**Cross-module:** entirius-django-regional, entirius-django-utils, entirius-py-idx-normalizator,
entirius-py-process-logger; extras: `bookings` (entirius-py-google-calendar-sdk),
`google-ads` (entirius-py-google-ads-sdk), `email` (entirius-django-email)

## Gotchas

- `PRIVATE_DIR` raises `OSError` at import time if unset
- `ContactForm.id` is a 12-digit random **string** PK, not an integer
- Attachments stored in `CUSTOM_FORM_ATTACHMENT_DIR` outside `MEDIA_ROOT` — require download view
- v1 and v2 coexist: v1 uses marshmallow + function views, v2 uses Pydantic + DRF ViewSets
- Public v2 API returns `(AnonymousUser, channel)` from auth — access channel via `request.auth`
- Keys: `utils/api_keys.py` `key_is_valid` is the one check (v1 decorator, v2 auth classes). With `django_access`
  installed it calls `verify_api_key` (scopes `contact_forms.submit` / `contact_forms.booking`) and never reads
  `APIKey`; legacy keys work only as imported tokens. Soft dependency — never in `pyproject.toml`.
- Throttles (`api/public/throttling.py`): never key material in a cache key; with access per token + visitor plus a
  per-token ceiling (`<scope>_token`) — see `docs/configuration.md` § Throttles.
- Calendar/Ads SDK imports are lazy behind the `bookings` / `google-ads` extras; without them the
  local-only backend and a no-op uploader are used
