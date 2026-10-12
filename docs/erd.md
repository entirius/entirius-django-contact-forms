---
title: "Contact Forms: Database Diagrams"
description: "Auto-generated ER diagrams for the Contact Forms module."
sidebar:
  badge:
    text: "Auto-gen"
    variant: "note"
---

:::caution[Auto-generated]
These diagrams are auto-generated from Django model introspection.
Do not edit. Run `make erd` in entirius-docker to regenerate.
:::

## Contact Forms

```d2 layout=elk
Channel: {
  shape: sql_table
  style.fill: "#00ACC1"
  style.stroke: "#12141A"
  style.font-color: "#EBEDF2"
  id: int {constraint: primary_key}
  idx: varchar {constraint: unique}
  "label": varchar {constraint: unique}
  default_language_id: int {constraint: foreign_key}
  admin_email: varchar
}

ContactForm: {
  shape: sql_table
  style.fill: "#00ACC1"
  style.stroke: "#12141A"
  style.font-color: "#EBEDF2"
  id: varchar {constraint: primary_key}
  channel_id: int {constraint: foreign_key}
  language_id: int {constraint: foreign_key}
  slug: varchar
  email: varchar
  body: jsonb
  type: varchar
  code: varchar
}

ContactFormAttachment: {
  shape: sql_table
  style.fill: "#00ACC1"
  style.stroke: "#12141A"
  style.font-color: "#EBEDF2"
  id: int {constraint: primary_key}
  contact_form_id: int {constraint: foreign_key}
  name: varchar
  attachment: varchar
}

APIKey: {
  shape: sql_table
  style.fill: "#00ACC1"
  style.stroke: "#12141A"
  style.font-color: "#EBEDF2"
  id: int {constraint: primary_key}
  channel_id: int {constraint: foreign_key}
  key: varchar
  scope: varchar
}

FormType: {
  shape: sql_table
  style.fill: "#00ACC1"
  style.stroke: "#12141A"
  style.font-color: "#EBEDF2"
  id: int {constraint: primary_key}
  channel_id: int {constraint: foreign_key}
  code: varchar
  "label": varchar
  is_default: bool
}

FormNotificationConfig: {
  shape: sql_table
  style.fill: "#00ACC1"
  style.stroke: "#12141A"
  style.font-color: "#EBEDF2"
  id: int {constraint: primary_key}
  channel_id: int {constraint: foreign_key}
  form_type: varchar
  slug: varchar
  send_email: bool
  send_client_copy: bool
  recipient_email: varchar
}

Language: {
  shape: sql_table
  style.fill: "#484B57"
  style.stroke: "#1A1C25"
  style.stroke-dash: 3
  style.font-color: "#9A9CAA"
  id: int {constraint: primary_key}
  label: "Language (External: django_regional)"
}



Channel.default_language_id -> Language.id: {style.stroke: "#484B57"}

ContactForm.channel_id -> Channel.id: {style.stroke: "#00ACC1"}

ContactForm.language_id -> Language.id: {style.stroke: "#484B57"}

ContactFormAttachment.contact_form_id -> ContactForm.id: {style.stroke: "#00ACC1"}

APIKey.channel_id -> Channel.id: {style.stroke: "#00ACC1"}

FormType.channel_id -> Channel.id: {style.stroke: "#00ACC1"}

FormNotificationConfig.channel_id -> Channel.id: {style.stroke: "#00ACC1"}
```

## Bookings, Leads & Google Ads

```d2 layout=elk
ContactFormsSettings: {
  shape: sql_table
  style.fill: "#00ACC1"
  style.stroke: "#12141A"
  style.font-color: "#EBEDF2"
  id: int {constraint: primary_key}
  bookings_enabled: bool
  google_ads_enabled: bool
}

BookingConfig: {
  shape: sql_table
  style.fill: "#00ACC1"
  style.stroke: "#12141A"
  style.font-color: "#EBEDF2"
  id: int {constraint: primary_key}
  channel_id: int {constraint: foreign_key}
  enabled: bool
  provider: varchar
  service_account_credentials_path: varchar
  impersonate_email: varchar
  calendar_id: varchar
  slot_duration_minutes: int
}

Booking: {
  shape: sql_table
  style.fill: "#00ACC1"
  style.stroke: "#12141A"
  style.font-color: "#EBEDF2"
  id: int {constraint: primary_key}
  contact_form_id: int {constraint: foreign_key}
  provider: varchar
  calendar_event_id: varchar
  meet_link: varchar
  meeting_start: timestamp
  meeting_end: timestamp
  timezone: varchar
}

Lead: {
  shape: sql_table
  style.fill: "#00ACC1"
  style.stroke: "#12141A"
  style.font-color: "#EBEDF2"
  id: int {constraint: primary_key}
  contact_form_id: int {constraint: foreign_key}
  name: varchar
  email: varchar
  phone: varchar
  company: varchar
  source_type: varchar
  contact_date: timestamp
}

LeadCreationRule: {
  shape: sql_table
  style.fill: "#00ACC1"
  style.stroke: "#12141A"
  style.font-color: "#EBEDF2"
  id: int {constraint: primary_key}
  channel_id: int {constraint: foreign_key}
  form_type: varchar
  slug: varchar
  enabled: bool
  source_type: varchar
}

GoogleAdsConfig: {
  shape: sql_table
  style.fill: "#00ACC1"
  style.stroke: "#12141A"
  style.font-color: "#EBEDF2"
  id: int {constraint: primary_key}
  channel_id: int {constraint: foreign_key}
  enabled: bool
  customer_id: varchar
  login_customer_id: varchar
  oauth_refresh_token: varchar
  default_currency_code: varchar
  meeting_booked_action_id: varchar
}

OfflineConversionQueue: {
  shape: sql_table
  style.fill: "#00ACC1"
  style.stroke: "#12141A"
  style.font-color: "#EBEDF2"
  id: int {constraint: primary_key}
  lead_id: int {constraint: foreign_key}
  conversion_action_id: varchar
  conversion_action_label: varchar
  conversion_time: timestamp
  conversion_value: decimal
  currency_code: varchar
  conversion_environment: varchar
}

Channel: {
  shape: sql_table
  style.fill: "#484B57"
  style.stroke: "#1A1C25"
  style.stroke-dash: 3
  style.font-color: "#9A9CAA"
  id: int {constraint: primary_key}
  label: "Channel (See contact-forms diagram)"
}

ContactForm: {
  shape: sql_table
  style.fill: "#484B57"
  style.stroke: "#1A1C25"
  style.stroke-dash: 3
  style.font-color: "#9A9CAA"
  id: int {constraint: primary_key}
  label: "ContactForm (See contact-forms diagram)"
}



BookingConfig.channel_id -> Channel.id: {style.stroke: "#484B57"}

Booking.contact_form_id -> ContactForm.id: {style.stroke: "#484B57"}

Lead.contact_form_id -> ContactForm.id: {style.stroke: "#484B57"}

LeadCreationRule.channel_id -> Channel.id: {style.stroke: "#484B57"}

GoogleAdsConfig.channel_id -> Channel.id: {style.stroke: "#484B57"}

OfflineConversionQueue.lead_id -> Lead.id: {style.stroke: "#00ACC1"}
```
