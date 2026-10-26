# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from django.apps import AppConfig


class DjangoFormsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "django_contact_forms"
    verbose_name = "Contact Forms"
    is_volkanos = True
    # Copied 1:1 from entirius-django-access cf538d2 catalogue defaults;
    # the access defaults stay until this module's release.
    access_areas = [
        {"key": "contact_forms.submissions", "label": "Form submissions and bookings", "sensitive": ("pii",)},
        {"key": "contact_forms.leads", "label": "Form leads and ad conversions", "sensitive": ("pii",)},
        {"key": "contact_forms.settings", "label": "Form notifications and integrations"},
    ]
    access_token_scopes = [
        {
            "key": "contact_forms.submit",
            "label": "Submit contact forms",
            "publishable": True,
            "routes": (
                "/api/contact/{version}/{channel_idx}/contact_form/**",
                "/api/contact-forms/v2/{channel_idx}/form-types/",
                "/api/contact-forms/v2/{channel_idx}/submit/**",
            ),
        },
        {
            "key": "contact_forms.booking",
            "label": "Booking slots and bookings",
            "publishable": True,
            "routes": ("/api/contact-forms/v2/{channel_idx}/bookings/**",),
        },
    ]
    # Every admin view carries its access_area; no route needs a path rule.
    access_route_rules = []

    def ready(self) -> None:
        from django_contact_forms.signals import lead_status_changed
        from django_contact_forms.signals.handlers import on_lead_status_changed

        lead_status_changed.connect(on_lead_status_changed, dispatch_uid="contact_forms.on_lead_status_changed")
