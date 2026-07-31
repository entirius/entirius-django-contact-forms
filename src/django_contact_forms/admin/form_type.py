# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from django.contrib import admin

from django_contact_forms.models.form_type import FormType


@admin.register(FormType)
class FormTypeAdmin(admin.ModelAdmin):
    list_display = ["channel", "code", "label", "is_default"]
    list_filter = ["channel__idx", "is_default"]
    list_select_related = ["channel"]
    search_fields = ["code", "label"]
    ordering = ["channel__idx", "code"]
