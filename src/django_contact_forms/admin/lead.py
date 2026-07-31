# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from django.contrib import admin

from django_contact_forms.models import Lead


@admin.register(Lead)
class LeadAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
        "email",
        "status",
        "source_type",
        "campaign_name",
        "deal_value",
        "ads_conversion_imported",
        "contact_date",
    )
    list_filter = ("status", "source_type", "attribution_method", "ads_conversion_imported")
    search_fields = ("name", "email", "company", "gclid", "campaign_name")
    readonly_fields = (
        "hashed_email",
        "ads_conversion_imported",
        "ads_imported_at",
        "status_changed_at",
        "created_at",
        "modified_at",
    )
    date_hierarchy = "contact_date"
