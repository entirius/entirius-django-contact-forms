---
title: Multilang Emails
description: How contact-forms emails are routed, translated, and rendered.
---

How contact-forms emails are routed, translated, and rendered on the Volkanos platform. Applies to booking confirmations, booking admin notifications, and generic contact-form submissions. The same rules govern every module that sends email — accounts, checkout, returns, agreements — so once you know this page, you know the whole platform's email story.

## TL;DR

- Every email goes through a `django_email.service.EmailService` subclass.
- `EmailService.__init__(language, channel_idx)` activates Django i18n (`django.utils.translation.activate(language)`), loads branding, and picks a `LangChannelConfig` for per-language header/footer copy.
- Templates use `{% trans %}` / `{% blocktrans %}` with translations in `django-email/locale/{en,pl,de}/LC_MESSAGES/django.po`.
- The submitter's language wins for booker-facing emails. Operator-facing emails render in the channel's default language.

## Language resolution chain

```
     request body {"language": "pl"}
                │
                ▼
    ContactForm.language (FK → django_regional.Language)  ← persisted
                │
                ▼
    send_booking_notifications (or similar)
                │
                ▼
   booker:  cf.language.iso2  →  channel.default_language.iso2  →  None
   admin:                         channel.default_language.iso2  →  None
                │
                ▼
    EmailService.__init__(language=..., channel_idx=...)
                │
                ▼
   _activate_language():
     if language in EMAIL_AVAILABLE_LANGUAGES  →  activate it
     else                                       →  activate EMAIL_DEFAULT_LANGUAGE
```

`EMAIL_AVAILABLE_LANGUAGES` defaults to `["en", "pl"]`. `EMAIL_DEFAULT_LANGUAGE` defaults to `"pl"`.

Pass `None` when you don't know — the service handles the fallback and logs the activated language on its `ProcessLogger`. Never raise 400 for an unsupported language; fall back silently.

## Who reads what, in which language

| Email | Recipient | Language source |
|---|---|---|
| Booking confirmation | Booker | `ContactForm.language` → `channel.default_language` |
| Booking admin notification | Operator | `channel.default_language` |
| Generic contact-form submission | Operator | `channel.default_language` |

Rationale: a Polish booker expects a Polish confirmation; the sales desk configures its inbox locale once per channel and wants every notification in that locale regardless of who submitted the form.

## Where everything lives

```
django-email/
├── src/django_email/
│   ├── service/contact_forms/
│   │   ├── booking_confirmation.py         BookingConfirmationEmail
│   │   ├── booking_admin_notification.py   BookingAdminNotificationEmail
│   │   └── contact_form_submission.py      ContactFormSubmissionEmail
│   ├── models/contact_forms/
│   │   ├── booking_confirmation.py         ContactFormsBookingConfirmation
│   │   ├── booking_admin_notification.py   ContactFormsBookingAdminNotification
│   │   └── contact_form_submission.py      ContactFormsSubmission
│   ├── admin/contact_forms/                Grappelli registrations (3×)
│   ├── templates/django_contact_forms/email/
│   │   ├── booking_confirmation.{html,txt}
│   │   ├── booking_admin_notification.{html,txt}
│   │   └── contact_form_submission.{html,txt}
│   ├── language.py                          resolve_email_language(requested, channel)
│   └── locale/{en,pl,de}/LC_MESSAGES/       translations

django-contact-forms/
├── src/django_contact_forms/
│   ├── services/
│   │   ├── booking_service.py
│   │   │   └── _persist_contact_form_and_booking  ← sets ContactForm.language
│   │   ├── booking_notification_service.py
│   │   │   └── send_booking_notifications  ← instantiates both subclasses
│   │   └── contact_form_service.py
│   │       └── create_submission  ← already accepted language pre-2.1.0
│   └── tasks/send_contact_form_email.py
│       (Celery wrapper around ContactFormSubmissionEmail)
```

## Operator customization

Three Grappelli screens let operators override subject + intro / closing copy per channel + per language without a code deploy:

- **\[Contact Forms\] Booking Confirmation** — booker email
- **\[Contact Forms\] Booking Admin Notification** — admin booking alert
- **\[Contact Forms\] Submission** — generic form notification

Each has four fields:

- `channel` (FK) — which channel this applies to
- `language` (FK, nullable) — `null` = applies to all languages for this channel (fallback); a specific language overrides for that language only
- `subject` — overrides the gettext default (`_("Your booking is confirmed")`)
- `intro_copy` — paragraph above the facts table
- `closing_copy` — paragraph below the meet link

Left blank → the template falls back to the gettext string shipped in `locale/{lang}/LC_MESSAGES/django.po`.

## Adding a new translated email type

Recipe (mirrors how booking was added):

1. Ship both a `.html` and a `.txt` template in `django_email/templates/{module}/email/{name}.{html,txt}`. Start with `{% load i18n %}` + `{% include 'base/header.html' %}` + `{% include 'base/footer.html' %}`. Wrap every visible string in `{% trans %}` / `{% blocktrans %}`.

2. In `django_email/settings.py`, add a path setting:

   ```python
   FOO_EMAIL_TEMPLATE_PATH = getattr(settings, "FOO_EMAIL_TEMPLATE_PATH", "{module}/email/foo")
   ```

3. In `django_email/template.py`, extend `EmailTemplate.TemplateList`:

   ```python
   # MODULE
   FOO = settings.FOO_EMAIL_TEMPLATE_PATH
   ```

4. Create an operator-editable model in `django_email/models/{module}/foo.py` with `channel` + `language` + `subject` + copy fields, and `subject_as_dict()` / `variables_as_dict()` methods. Export from `models/__init__.py`. Run `makemigrations django_email`.

5. Register in `django_email/admin/{module}/foo.py` (copy an existing `[Contact Forms] Booking Confirmation` admin and rename).

6. Create the `EmailService` subclass in `django_email/service/{module}/foo.py`:

   ```python
   from django.utils.translation import gettext as _

   from django_email.models import FooModel
   from django_email.service import EmailService
   from django_email.template import EmailTemplate


   class FooEmail(EmailService):
       EMAIL_NAME = "FOO"
       model: FooModel
       model_class = FooModel

       def get_subject(self) -> str:
           return _("Default subject string")

       def prepare_context(self, payload: dict) -> dict:
           ctx = {"subject": self.get_subject(), **payload}
           ctx.update(self.channel.variables_as_dict(self.language))
           if self.model:
               ctx.update(self.model.subject_as_dict())
               ctx.update(self.model.variables_as_dict())
           return ctx

       def send(self, email: list[str], payload: dict) -> None:
           ctx = self.prepare_context(payload)
           message, html_message = EmailTemplate(template=EmailTemplate.TemplateList.FOO, context=ctx).render()
           self.domain.send_email(
               subject=ctx.get("subject", self.get_subject()),
               message=message,
               recipient_list=email,
               html_message=html_message,
           )
   ```

7. Add translations in `django_email/locale/pl/LC_MESSAGES/django.po` (and `en/` as identity). Run `django-admin compilemessages` inside the container.

8. Call it from the module that owns the trigger:

   ```python
   FooEmail(language="pl", channel_idx="ecomwww").send(email=[...], payload={...})
   ```

   Use `translation.override(lang)` in tests to assert the rendered body.

## Testing

```python
from django.core import mail
from django.utils import translation


def test_booker_email_renders_polish(monkeypatch, channel):
    # arrange — Polish booker
    booking_result = make_booking(channel, language="pl")

    # act
    send_booking_notifications(channel=channel, result=booking_result)

    # assert
    assert len(mail.outbox) >= 1
    booker_email = next(m for m in mail.outbox if booking_result.contact_form.email in m.to)
    assert "Zarezerwowaliśmy" in booker_email.alternatives[0][0]
```

Patch the Google Calendar backend in booking tests — never hit the live API. See `tests/test_service_booking.py` for existing patches.

## Anti-patterns

- **Don't ship per-language template files** (`foo_pl.html`, `foo_en.html`). Use `{% trans %}` + a shared template. Language-specific files break the `EmailService` contract and double the maintenance surface.
- **Don't hardcode `language="en"` caller-side.** The agreements newsletter signup had this bug pre-1.0.1 — every Polish subscriber got an English confirmation regardless of channel. Fixed in 1.0.1.
- **Don't bypass `EmailService`.** If you need `activate()`, branding resolution, and per-channel SMTP — they're all in the base class. Write a subclass; don't reimplement.
- **Don't render emails in a Celery task body.** The task is a thin async wrapper; delegate to an `EmailService` subclass. See `django_contact_forms/tasks/send_contact_form_email.py` for the shape.
- **Don't return 400 for unsupported languages.** The fallback chain is silent: requested → channel default → `EMAIL_DEFAULT_LANGUAGE`.
