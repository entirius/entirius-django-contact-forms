# Changelog

## Unreleased

- Keys verified by django-access when installed: v1 `@channel_view` (scope `contact_forms.submit` or
  `contact_forms.booking`, as today) and v2 `APIKeyAuthentication` / `BookingAPIKeyAuthentication` (their own scope)
  check access tokens through `verify_api_key`, channel pin included, never the `APIKey` table. `request.auth` stays
  the `Channel`. Without django-access nothing changes. `forms-generate-api-key` then refuses and names
  `access_token create`; the key admin becomes read-only.
- Throttles never put key material in a cache key: without django-access the per-key bucket is named by a SHA-256
  prefix of the key. With django-access the public routes bucket per token + client address, under a per-token
  ceiling (scopes `contact_forms_submit_token`, `contact_forms_form_types_token`, `contact_forms_booking_token`;
  unconfigured 20 × the visitor rate), so one visitor holding the public key cannot silence the form for all.
- The key admin shows only the last four characters of a key.

## 3.0.0 — 2026-07-31

- Initial public release: channel-scoped contact form submissions with JSON
  body storage, API-key authentication, and a per-type/slug notification
  config system.
- Form types: per-channel `FormType` catalog with public and admin endpoints;
  submissions are normalized against the catalog and routed by resolved type.
- Optional client copy: the submitter receives a confirmation rendered by
  django-email in their own language.
- Bookings (optional `[bookings]` extra): calendar-backed booking slots with
  Google Calendar and database-backed `local` providers, per-channel row
  locking against double booking, and booker/admin confirmation emails.
- Leads: attribution capture (gclid, UTM, landing page), status FSM, and
  admin endpoints; opt-in `LeadCreationRule` decides which submissions spawn
  a Lead.
- Google Ads offline conversions (optional `[google-ads]` extra): queued
  uploads on lead status changes via the google-ads-sdk.
- Multilang emails: booker confirmations in the booker's language, admin
  notifications in the channel default; language resolution delegated to
  `django_email.language.resolve_email_language`.
- Public endpoints rate-limited; service-level throttle overrides work via
  `fallback_rate`.
- v2 Admin + Public API with Pydantic schemas and OpenAPI docs.
- Migrations squashed into a single initial migration for the Entirius epoch.
