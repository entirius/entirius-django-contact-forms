# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from django.contrib import admin

from django_contact_forms.models import GoogleAdsConfig


@admin.register(GoogleAdsConfig)
class GoogleAdsConfigAdmin(admin.ModelAdmin):
    list_display = ("channel", "enabled", "customer_id", "default_currency_code")
    list_filter = ("enabled", "default_currency_code")
    search_fields = ("channel__idx", "customer_id")
    fieldsets = (
        ("Channel", {"fields": ("channel", "enabled")}),
        ("Account", {"fields": ("customer_id", "login_customer_id", "default_currency_code")}),
        (
            "OAuth (refresh token encrypted at rest)",
            {
                "fields": ("oauth_refresh_token",),
                "description": "Paste the OAuth2 refresh token. Stored encrypted via Fernet.",
            },
        ),
        (
            "Conversion-action mapping",
            {
                "fields": (
                    "meeting_booked_action_id",
                    "meeting_booked_value",
                    "qualified_lead_action_id",
                    "qualified_lead_value",
                    "won_deal_action_id",
                ),
                "description": "Won deal value comes from Lead.deal_value at upload time.",
            },
        ),
    )
