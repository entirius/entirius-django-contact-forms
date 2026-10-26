# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from django.contrib import admin

from django_contact_forms.models import APIKey
from django_contact_forms.utils.api_keys import access_installed, mask_key


@admin.register(APIKey)
class APIKeyAdmin(admin.ModelAdmin):
    """Keys show only their last four characters; with django_access installed they are read-only (tokens rule)."""

    model = APIKey
    list_display = ["masked_key", "channel", "scope"]
    exclude = ("key",)
    readonly_fields = ("masked_key",)

    @admin.display(description="key")
    def masked_key(self, obj) -> str:
        return mask_key(obj.key)

    def has_add_permission(self, request) -> bool:
        return not access_installed() and super().has_add_permission(request)

    def has_change_permission(self, request, obj=None) -> bool:
        return not access_installed() and super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None) -> bool:
        return not access_installed() and super().has_delete_permission(request, obj)
