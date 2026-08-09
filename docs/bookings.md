---
title: Bookings
description: Public calendar booking endpoint backed by Google Calendar with a Meet link, persisted as ContactForm + Booking + Lead.
sidebar:
  label: Bookings
---

The booking widget lets a website pick an available slot, create a calendar event with a Google Meet link, and start a Lead in one round trip. The contract is the same for every channel; per-channel `BookingConfig` rows decide which calendar to write to and what the slot rules are.

## When to use

Turn this on for any channel that needs scheduled consultations, demos, or phone calls. Don't use it for arbitrary one-off forms — that's what the contact-form submit endpoint is for. A booking always produces a Lead; a contact-form submission can but doesn't have to.

## Enable it

Three switches must all be on:

1. Singleton `ContactFormsSettings.bookings_enabled = True` (Django admin → Contact Forms settings)
2. Per-channel `BookingConfig.enabled = True`
3. At least one `APIKey` for the channel with `scope = "booking"` — generate via `python manage.py forms-generate-api-key` (extend with `--scope=booking` argument; today create one in the admin)

## Endpoints

```
GET  /api/contact-forms/v2/{channel_idx}/bookings/slots/?date_from=YYYY-MM-DD&days=N
POST /api/contact-forms/v2/{channel_idx}/bookings/
```

Both require the `X-API-KEY` header with a key whose `scope = "booking"`. A contact-form-scoped key is rejected — defense in depth so a key meant for the public submit form can't drive the booking widget.

### List slots

```
GET /api/contact-forms/v2/default-europe/bookings/slots/?days=14
X-API-KEY: ...
```

```json
{
  "timezone": "Europe/Warsaw",
  "slot_duration_minutes": 30,
  "days": [
    {
      "day": "2026-04-22",
      "slots": [
        { "start": "09:00:00", "end": "09:30:00", "available": true },
        { "start": "09:30:00", "end": "10:00:00", "available": false }
      ]
    }
  ]
}
```

`weekdays_only`, `start_hour`, `end_hour`, and `slot_duration_minutes` come from `BookingConfig`. The horizon is capped at `days_ahead` regardless of the `?days` parameter.

### Create a booking

```
POST /api/contact-forms/v2/default-europe/bookings/
X-API-KEY: ...
Content-Type: application/json

{
  "booking_date": "2026-04-25",
  "booking_time": "10:30",
  "name": "Jan Kowalski",
  "email": "jan@example.com",
  "phone": "+48123456789",
  "gclid": "CjwK...",
  "utm_source": "google",
  "utm_campaign": "spring-promo"
}
```

```json
{
  "status": "booked",
  "event_id": "abcdef123",
  "meet_link": "https://meet.google.com/abc-defg-hij",
  "meeting_start": "2026-04-25T10:30:00+02:00",
  "meeting_end": "2026-04-25T11:00:00+02:00",
  "contact_form_id": "123456789012",
  "lead_id": 42
}
```

Status codes:

| Code | When |
|---|---|
| 201 | Created |
| 400 | Bookings disabled, weekend (when `weekdays_only`), out of hours, in the past, beyond horizon, schema validation |
| 401 | Missing or wrong API key, or wrong scope |
| 409 | Slot was free at validation but became busy by the time we tried to book it |
| 502 | Google Calendar API failed |

## Google Calendar setup

The Google Calendar backend uses a service account with **domain-wide delegation**. One-time admin steps:

1. Create a Google Cloud project, enable the Calendar API.
2. Create a service account; download the JSON key.
3. In Google Workspace admin, grant the service account scope `https://www.googleapis.com/auth/calendar`.
4. Mount the JSON key inside the container, e.g. `/app/credentials/sa.json`.
5. In `BookingConfig`:
   - `service_account_credentials_path = "/app/credentials/sa.json"`
   - `impersonate_email = "bookings@yourdomain.com"` — events are created on this user's primary calendar so they own them and receive the invite.
   - `calendar_id = "primary"` (or a shared booking calendar — free-busy queries union both).
6. Flip `enabled = True`.

Free-busy queries always include the impersonated user's `primary`; if `calendar_id` is something else, that calendar is queried as well and busy periods from both are merged.

## Calendar providers

`BookingConfig.provider` picks the backend. Two options ship today.

### `google_calendar` (default)

Full integration with Google Calendar — see the setup section above. Requires the `[bookings]` extra (`google-calendar-sdk`) + a service-account JSON + domain-wide delegation. Events appear on the operator's real calendar; free-busy integrates with every other tenant user; Meet links are generated per booking.

### `local`

Database-only — no external API. Free-busy is derived from existing `Booking` rows scoped to the channel; `create_event` writes nothing external and returns an opaque `local-<uuid>` event id with an empty meet link. Pick this when:

- The tenant doesn't have Google Workspace, or doesn't want to hand us domain-wide delegation.
- You want a booking widget for an internal / private workflow where follow-up happens over email or phone (our booking-confirmation email covers this — see below).
- You're on staging / demo and don't want to mock the Google SDK.

What `local` **does not** do: push an event to anyone's real calendar, generate a Meet link, send Google Calendar invites. The booking-confirmation email this module sends to the booker is the only notification they receive.

### Concurrency

`booking_service.create_booking` takes a channel-level row lock (`SELECT … FOR UPDATE` on the `Channel` row) at the top of its transaction. Concurrent bookings for the same channel serialise — even when two requests pass `is_slot_free` nearly simultaneously, the second waits until the first commits, then sees the freshly-persisted `Booking` and raises `SlotUnavailableError`. Works for every backend; Google's own 409 handling remains as a second line of defense.

### Pluggable

To add Calendly or a generic webhook later: drop a new file in `services/calendar/backends/`, register the provider string in `services/calendar/factory.py`, and add the choice to `BookingConfig.Provider`. No changes to `booking_service.py` needed.

## Email notifications

Google Calendar API doesn't send invites when events are created by a service account, and the `local` provider doesn't talk to any calendar at all — so contact-forms sends its own emails after every successful booking.

### Booker confirmation — always sent

Every successful `POST /bookings/` dispatches a confirmation email to `request.email`. Subject: `"Your booking is confirmed — YYYY-MM-DD HH:MM <timezone>"`. Template: `django_contact_forms/email/booking_confirmation.html` (override via the `BOOKING_CONFIRMATION_TEMPLATE_HTML` setting). The template renders the meeting time, booker details, and the Meet link (or a generic "we'll be in touch" fallback when empty — useful for the `local` provider).

No toggle. Sales follow-up falls apart if the booker doesn't know the time was accepted.

### Admin notification — opt-in per channel

Admin notifications reuse the existing `FormNotificationConfig` fallback chain (exact → type-level → channel-level → global `CONTACT_FORM_SEND_ADMIN_EMAIL`), with `form_type="booking"`. To route booking admin notifications to a specific mailbox, create a row in Grappelli:

```
FormNotificationConfig
  channel         = <your channel>
  form_type       = "booking"
  slug            = ""
  send_email      = True
  recipient_email = "sales-desk@example.com"   # or blank for channel.admin_email
```

Same subject template as the booker email but prefixed with `"New booking — "` so operator inboxes can filter.

### Graceful degradation

Both dispatches go through the same `notification_service.dispatch_email` pipeline the plain submit endpoint uses — they inherit its degradation behavior: missing `django-email` or un-migrated schema falls back to plain SMTP; SMTP down is logged and swallowed. **A notification failure never turns a successful booking into a 5xx**; the booker walks away with a 201 and the Booking row exists regardless.

## Storage shape

A successful booking writes three rows in one transaction:

```
ContactForm  type="booking", body holds the full booking payload + UTM
   └── Booking            calendar_event_id, meet_link, meeting_start/end
   └── Lead               source_type="calendar", attribution from the request
```

The Lead is created via `lead_service.create_lead` so the standard `lead_status_changed` signal fires. With Google Ads enabled, that triggers an `OfflineConversionQueue` row for the "Meeting Booked" action — see [Ads Conversions](../ads-conversions/).

## Admin API

Read-only. Bookings are owned by the calendar; the CMS reads but never writes. JWT + `IsAdminUser`. Base path: `/api/contact-forms/v2/admin/`.

```
GET  bookings/?channel=&date_from=&date_to=&lead_status=&search=
GET  bookings/{pk}/
```

The list is paginated (`AdminPageNumberPagination`, 20 per page, max 100) and ordered by `-meeting_start`. `date_from` / `date_to` accept ISO-8601 datetimes or bare dates and filter on `meeting_start`. `lead_status` narrows to bookings whose **most recent** linked Lead is in the given status — useful for pulling "upcoming meetings with qualified leads" or "bookings that actually closed". `search` matches the contact form email, id, or the calendar event id.

Every response embeds a `linked_lead` summary (id, status, name, email, deal_value, ads_conversion_imported) or `null` when the Booking's ContactForm never spawned a Lead. The CMS uses this to show a status badge inline and jump straight to the Lead detail.

Each field shape is canonical via the Pydantic response schemas in `schemas/responses/booking.py` — the auto-generated OpenAPI reference at `/api/cms/` is the source of truth; don't hand-write contracts here.

## Channel integrations endpoint

The CMS needs to know whether a channel has Google Ads + Bookings actually enabled (global toggle AND per-channel config) before it can render things like "Conversion will be pushed to Google Ads". That check is served here:

```
GET  channels/{channel_idx}/integrations/
```

Returns `{channel_idx, google_ads_enabled, bookings_enabled}`. Each flag is the logical AND of `ContactFormsSettings.{flag}` and the per-channel `GoogleAdsConfig.enabled` / `BookingConfig.enabled`. 404 when the channel does not exist.

The CMS hits this once per Lead detail (to gate the Mark-as-Won push-to-Google-Ads hint) and once per Bookings panel load. Operators manage the underlying config in Grappelli, not in the CMS.
