# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from django.contrib import admin

from django_contact_forms.models import Booking


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ("id", "contact_form", "calendar_event_id", "meeting_start", "provider", "created_at")
    list_filter = ("provider", "timezone")
    search_fields = ("calendar_event_id", "meet_link", "contact_form__email")
    readonly_fields = ("created_at", "modified_at")
