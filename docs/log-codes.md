---
title: Log Codes
description: Error and warning codes logged by django-contact-forms views and the email dispatch task.
---

Codes are logged via `ProcessLogger` and attached to exceptions. Check application logs (e.g. Graylog) filtered by these codes to diagnose submission or delivery failures.

| Code | Level | Where | Description |
|---|---|---|---|
| 4003 | Error | View / Celery task | General attachment storage failure; or `ContactForm` not found in the email task. |
| 4004 | Error | View | `ContactForm.objects.create()` failed — general database error on form save. |
| 4005 | Error | View | JSON body exceeds `FORMS_MAX_JSON_MB_SIZE`. Raised as `JSONTooLargeException`. |
| 4006 | Warning | View | Request `Content-Type` is not `multipart/form-data` when files are expected. Attachments skipped, form still saved. |
| 4008 | Error | View | Number of attachments exceeds `FORMS_MAX_ATTACHMENT_COUNT`. |
| 4009 | Error | View | Total attachment size exceeds `FORMS_MAX_ATTACHMENT_MB_SIZE`. |
| 4010 | Error | Celery task | SMTP error in `send_contact_form_email`. Email was not sent. |
| 4011 | Error | View | `ContactFormPayload.body` is a string that cannot be parsed as JSON. |

## Notes

- Code **4006** is a warning, not a fatal error — the form submission is saved without attachments and the email task is still queued.
- Code **4010** does not re-raise the exception for generic `Exception` catches, meaning the Celery task completes without retrying. Check broker and SMTP configuration if this code appears repeatedly.
- Codes **4008** and **4009** abort the entire submission — the `ContactForm` record is saved but no attachments are stored, and `BadRequest` is returned to the caller.
