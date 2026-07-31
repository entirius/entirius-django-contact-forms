# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from django.contrib import admin

from django_contact_forms.models import ContactFormsSettings


@admin.register(ContactFormsSettings)
class ContactFormsSettingsAdmin(admin.ModelAdmin):
    list_display = ("__str__", "bookings_enabled", "google_ads_enabled")

    def has_add_permission(self, request):
        return not ContactFormsSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False
