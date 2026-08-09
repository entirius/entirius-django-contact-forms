# Changelog

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
