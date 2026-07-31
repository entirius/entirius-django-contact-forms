# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from django.contrib import admin

from django_contact_forms.models import BookingConfig, BookingTimeWindow


class BookingTimeWindowInline(admin.TabularInline):
    model = BookingTimeWindow
    extra = 1
    fields = ("order", "start_time", "end_time")
    ordering = ("order", "start_time")


@admin.register(BookingConfig)
class BookingConfigAdmin(admin.ModelAdmin):
    inlines = [BookingTimeWindowInline]
    list_display = (
        "channel",
        "enabled",
        "provider",
        "calendar_id",
        "timezone",
        "weekdays_only",
        "fomo_enabled",
        "fomo_intensity",
    )
    list_filter = ("enabled", "provider", "weekdays_only", "fomo_enabled")
    search_fields = ("channel__idx", "calendar_id", "impersonate_email")
    fieldsets = (
        (None, {"fields": ("channel", "enabled", "provider")}),
        (
            "Google Calendar (provider=google_calendar only)",
            {
                "fields": ("service_account_credentials_path", "impersonate_email", "calendar_id"),
                "classes": ("collapse",),
            },
        ),
        (
            "Slot rules",
            {
                "fields": (
                    "slot_duration_minutes",
                    "days_ahead",
                    "weekdays_only",
                    "timezone",
                    "event_summary_template",
                ),
                "description": (
                    "Working hours are managed inline below — add ≥1 BookingTimeWindow per day. "
                    "Slots are generated independently within each window."
                ),
            },
        ),
        (
            "FOMO synthetic busy slots (cosmetic only — never blocks real bookings)",
            {
                "fields": ("fomo_enabled", "fomo_intensity", "fomo_blackout_full_days"),
                "description": (
                    "Adds fake busy slots to make the calendar look more occupied. "
                    "Capped at ~80% per day so visitors always see openings. "
                    "Today and tomorrow are excluded from full-day blackouts so 'fresh availability' "
                    "urgency works."
                ),
            },
        ),
    )

    def save_model(self, request, obj, form, change) -> None:
        # Run clean() so service_account_credentials_path is validated against
        # CONTACT_FORMS_CREDENTIALS_DIR (path traversal defense). Django admin
        # invokes ModelForm.clean() but not Model.clean() by default.
        obj.full_clean()
        super().save_model(request, obj, form, change)
