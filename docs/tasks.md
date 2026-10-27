---
title: Celery Tasks
description: Celery tasks of django-contact-forms and their queues.
---

**`send_contact_form_email`** — Queue: `contact_forms`. Thin async wrapper
around django-email service classes. `send_admin` (default True) sends the
admin notification via `ContactFormSubmissionEmail`; `send_client_copy`
(default False) additionally sends the submitter copy via
`ContactFormClientCopyEmail`. Controlled by `notification_service` in v2, by
`CONTACT_FORM_SEND_ADMIN_EMAIL` in v1. Deprecated kwargs
(`template_html_path`, `subject`, `extra_context`) remain in the signature
for backward compatibility with previously enqueued tasks but are ignored.
Context handed to django-email (`_submission_context()`): `form_id` (the submission id, for the
`<contact_form_id>` subject token), `form_email`, `form_slug`, `form_type`, `form_code`, `form_body` (readable
`Label: value` text from `utils/email_body.body_text`) and `form_body_rows` (`BodyRow(label, value)` list from
`utils/email_body.body_rows`, one table row per field in django-email 4.3.0+).

**`upload_pending_conversions`** — Queue: `contact_forms_conversions`. Batch-uploads
queued `OfflineConversionQueue` rows via the `google-ads` extra (lazy import);
retries with backoff (`max_retries=3`).
