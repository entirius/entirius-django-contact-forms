# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from django.apps import AppConfig


class DjangoFormsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "django_contact_forms"
    verbose_name = "Contact Forms"
    is_volkanos = True

    def ready(self) -> None:
        from django_contact_forms.signals import lead_status_changed
        from django_contact_forms.signals.handlers import on_lead_status_changed

        lead_status_changed.connect(on_lead_status_changed, dispatch_uid="contact_forms.on_lead_status_changed")
