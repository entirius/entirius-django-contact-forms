# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Thin signal receivers — delegate to services per python/django-signals.md rule."""

from django_contact_forms.models import Lead


def on_lead_status_changed(sender, lead: Lead, old_status: str | None, new_status: str, **kwargs) -> None:
    """Delegate to the conversions service. Service decides whether to enqueue based on toggles."""
    from django_contact_forms.services.conversions import queue_service

    queue_service.enqueue_for_lead(lead=lead, old_status=old_status, new_status=new_status)
