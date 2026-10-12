# AGENTS.md

`entirius-django-contact-forms` (Django app `django_contact_forms`) — forms module of Entirius: channel-scoped
contact form submissions with file attachments, per-type email notification config, booking calendar with optional
Google Calendar backend, lead tracking with Google Ads offline-conversion uploads, and async email dispatch.
Dual API surface: v1 (legacy function-based) + v2 (DRF ViewSets, Pydantic, drf-spectacular).

## Commands

| Command | Meaning |
|---|---|
| `make install` | sync dependencies (uv, incl. extras) |
| `make check` | lint + format-check (ruff) |
| `make fix` | auto-fix lint + format |
| `make test` | test suite (pytest) |
| `make test-legacy` | test suite without django_access (legacy key path) |

Tests need PostgreSQL: set `DATABASE_URL` (the default in `tests/settings.py` points at a local postgres).

## Conventions

- English only: code, docs, commits, branches, PRs.
- MPL-2.0: every non-trivial source file carries the license header (pre-commit inserts it).
- Toolchain: uv + ruff + hatchling + pytest; all config in `pyproject.toml`; `uv.lock` committed.
- Git flow: `master` (production) + `develop` (integration); changes land via PR; semver tag on `master`.
- Never rename the Django app `django_contact_forms` — app_label and DB table prefix are a public schema contract.
- Access: areas live on the AppConfig (`access_areas`, `access_route_rules`), every admin view carries
  `access_area`; a new admin route without one fails `tests/test_access_ownership.py`.
- Default: do not commit — git is the user's call.

### Commit Message Format

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
├── templates/base/                     # header/footer partials
├── apps.py / settings.py / urls.py     # v1 + v2 admin + v2 public URL includes
```

Layer rule: `API → Services → Models → DB`. No business logic in views.

| Topic | Where |
|---|---|
| Overview, submission flow, key concepts | `docs/index.md` |
| Data model | `docs/data-model.md`, `docs/erd.md` |
| API v2 (admin, public) and v1 (legacy) endpoints | `docs/api.md` |
| Settings, notification config, API keys, throttles, queues | `docs/configuration.md` |
| Form types, client copy | `docs/form-types.md` |
| Bookings, multi-window working hours, FOMO synthetic busy slots | `docs/bookings.md` |
| Leads | `docs/leads.md` |
| Google Ads conversions | `docs/ads-conversions.md` |
| Multilang emails | `docs/multilang-emails.md` |
| Celery tasks | `docs/tasks.md` |
| Log codes | `docs/log-codes.md` |
| Testing | `docs/testing.md` |
| ERD config for the docs ERD generator | `docs/erd-config.yaml` |

## Settings

| Setting | Default | Description |
|---------|---------|-------------|
| `PRIVATE_DIR` | **required** | Root for private file storage |

Every other setting has a default — reference in `docs/configuration.md` § Settings.

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
