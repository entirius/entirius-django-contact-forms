---
title: Leads
description: Sales pipeline entity created from ContactForm submissions or bookings, with a status FSM and attribution tracking.
sidebar:
  label: Leads
---

A Lead is a contact who became a sales prospect. Every Booking creates one; contact-form submissions create one too if the calling code asks for it. The Lead carries enough attribution to close the loop with Google Ads after the deal is won.

## Data model

`Lead` (FK → `ContactForm`):

| Field | Notes |
|---|---|
| `name`, `email`, `phone`, `company` | Contact (mirrored from the request, not the ContactForm) |
| `source_type` | `calendar`, `form`, `whatsapp`, `email`, `phone`, `other` |
| `contact_date` | When the lead arrived (defaults to now, indexed for the admin list) |
| `gclid` | Google Click ID — primary identifier for Ads matching |
| `hashed_email` | SHA-256 of lower-cased email — enhanced-conversions fallback when no gclid (set automatically by `lead_service.create_lead`) |
| `attribution_method` | `gclid`, `enhanced`, `time_proximity`, `manual`, `unattributed` |
| `campaign_name`, `source`, `medium`, `landing_page` | UTM-style attribution metadata |
| `status` | FSM (see below) |
| `deal_value` | Decimal, set when transitioning to WON |
| `status_changed_at` | Auto-bumped on every transition |
| `notes` | Free-form sales notes |
| `ads_conversion_imported`, `ads_imported_at` | Flipped by the Google Ads uploader |
| `raw_data` | JSON payload — UTM raw, consent flag, language, anything that doesn't deserve a column |

## Status FSM

```
            ┌──────────────────────────────────────┐
            v                                      │
    NEW ──> CONTACTED ──> QUALIFIED ──> WON        │
     │           │             │                   │
     │           │             └──> LOST ──────────┘  (re-open via QUALIFIED or WON)
     │           └──> UNQUALIFIED                     (re-open via NEW)
     └──> UNQUALIFIED
```

Re-opening from terminal states is allowed because that's the sales reality — a "lost" deal can come back. Disallowed transitions raise `InvalidLeadTransitionError` (HTTP 400 with the explicit "Cannot transition Lead X from A to B" message).

Every successful transition sends the `lead_status_changed` signal with `(lead, old_status, new_status, channel_idx)`.

## Which submissions become Leads?

Two sources create Leads today:

1. **Bookings** — every successful `POST /bookings/` creates a Lead with `source_type="calendar"` unconditionally. No config required; if the booking widget is enabled, the Lead gets created.
2. **Plain submissions** — `POST /submit/` creates a Lead **only** when a matching `LeadCreationRule` row says so. Off by default for every channel and form.

Anything else — a phone call, a WhatsApp message, a CRM sync — creates Leads by calling `lead_service.create_lead()` directly. That's out of scope for contact-forms itself.

### `LeadCreationRule`

Operators opt specific forms into the pipeline via a rule table, using the same shape as `FormNotificationConfig`:

| Field | Purpose |
|---|---|
| `channel` | Scope — which channel this rule applies to |
| `form_type` | Form type ID from the URL (e.g., `request-a-quote`). Empty = channel-level rule |
| `slug` | Page/instance slug. Empty = type-level rule |
| `enabled` | Toggle without deleting the row |
| `source_type` | Value written to `Lead.source_type` when this rule fires. Defaults to `form`; set to `whatsapp` / `phone` / etc. to tag leads by origin |

### Fallback chain

Lookup order, same as `FormNotificationConfig`:

```
exact (channel, type, slug)
  → type-level (channel, type, "")
    → channel-level (channel, "", "")
      → off
```

The first match **wins**, even if `enabled=False`. That means a specific `(channel, "complaint", "contact-us")` rule with `enabled=False` blocks Lead creation for exactly that form, while a broader enabled rule above keeps working for everything else under the same type. There is **no** global default — Lead creation from plain submissions is opt-in only.

### Attribution from the body

When a rule fires, `lead_creation_rule_service.extract_attribution()` pulls known keys from `ContactForm.body` (the JSON blob the submitter sent) and forwards them to `lead_service.create_lead`:

| Body key | Lead field | Notes |
|---|---|---|
| `name`, `phone`, `company`, `message` | same | Contact details |
| `gclid` | `gclid` | Sets `attribution_method=gclid` |
| `utm_campaign` | `campaign_name` | |
| `utm_source` | `source` | |
| `utm_medium` | `medium` | |
| `landing_page` | `landing_page` | As-is |
| *(full body)* | `raw_data` | Anything else the submitter sent is preserved verbatim |

`hashed_email` is derived automatically by `lead_service.create_lead` when no `gclid` is present — same behavior as the booking pipeline.

### Configuration — Grappelli

No v2 admin API for this rule yet (v1 ships Grappelli-only). Operators manage it in Django admin: **Contact Forms → Lead Creation Rules**. Typical setups:

| Rule | Channel | Type | Slug | Enabled | Effect |
|---|---|---|---|---|---|
| Channel-wide catch-all | `default-europe` | `` | `` | `true` | Every plain submission on this channel spawns a Lead |
| Single type | `default-europe` | `request-a-quote` | `` | `true` | Quote requests spawn Leads; other forms don't |
| Disable one page | `default-europe` | `request-a-quote` | `partner-landing` | `false` | Suppress Lead on that specific page while keeping the type rule |

If you need per-submission opt-in ("I agree to be contacted" checkbox in the form), that's a future extension — not shipped today. The current rule operates purely at the `(channel, type, slug)` level.

## Admin API

JWT + `IsAdminUser` for all endpoints. Base path: `/api/contact-forms/v2/admin/`.

```
GET    leads/?channel=&status=&source_type=&search=
GET    leads/summary/?channel=
GET    leads/{pk}/
PATCH  leads/{pk}/                 # name, phone, company, deal_value, notes
POST   leads/{pk}/transition/      # body: {"new_status": "won", "deal_value": "1234.56"}
```

`?search=` filters across email, name, and gclid (case-insensitive). The list view is bounded by `AdminPageNumberPagination` (20 per page, max 100), `select_related` on the ContactForm + Channel for one query per page.

`summary/` returns counts per status:

```json
{
  "by_status": [
    { "status": "new", "count": 142 },
    { "status": "contacted", "count": 38 },
    { "status": "qualified", "count": 12 },
    { "status": "won", "count": 7 },
    { "status": "lost", "count": 21 }
  ]
}
```

Computed via `.values("status").annotate(count=Count("id"))` — one DB-level aggregate.

## Service usage

```python
from django_contact_forms.models import Lead
from django_contact_forms.services import lead_service

lead = lead_service.create_lead(
    contact_form=cf,
    source_type=Lead.SourceType.FORM,
    email="jan@example.com",
    gclid="CjwK...",
)
lead = lead_service.transition_status(lead=lead, new_status=Lead.Status.QUALIFIED)
lead = lead_service.transition_status(
    lead=lead,
    new_status=Lead.Status.WON,
    deal_value=Decimal("1234.56"),
)
```

Don't pass `status` to `update_lead` — it raises `ValueError` to force the explicit transition path.

## Email hashing rules

Set on save by `lead_service.create_lead` (and `update_lead`):

- If `gclid` is present → no hashing (gclid wins).
- Else if `email` is present and `hashed_email` is empty → set `hashed_email = sha256(email.lower().strip())`.
- Otherwise leave alone.

This is the enhanced-conversions fallback pattern. Google Ads can match the conversion to a click via the gclid; failing that, hashed email lets it match to a logged-in Google user.
