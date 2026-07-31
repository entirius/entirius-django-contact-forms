# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from django.contrib import admin

from django_contact_forms.models import APIKey


@admin.register(APIKey)
class APIKeyAdmin(admin.ModelAdmin):
    model = APIKey
    list_display = ["key"]
