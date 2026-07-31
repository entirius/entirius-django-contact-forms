# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from django.contrib import admin

from django_contact_forms.models.lead_creation_rule import LeadCreationRule


@admin.register(LeadCreationRule)
class LeadCreationRuleAdmin(admin.ModelAdmin):
    list_display = ["channel", "form_type", "slug", "enabled", "source_type"]
    list_filter = ["channel__idx", "enabled", "source_type"]
    search_fields = ["form_type", "slug"]
    ordering = ["channel__idx", "form_type", "slug"]
