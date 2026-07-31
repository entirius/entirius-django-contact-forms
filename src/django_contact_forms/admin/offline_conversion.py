# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import logging

from django.contrib import admin

from django_contact_forms.models import OfflineConversionQueue

logger = logging.getLogger(__name__)


@admin.register(OfflineConversionQueue)
class OfflineConversionQueueAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "lead",
        "conversion_action_label",
        "status",
        "conversion_value",
        "currency_code",
        "attempt_count",
        "imported_at",
    )
    list_filter = ("status", "currency_code", "conversion_action_label")
    # gclid/hashed_email removed from search to avoid email-presence enumeration
    # via DB audit logs. Channel idx via FK chain stays useful for ops.
    search_fields = ("conversion_action_id", "lead__email", "lead__contact_form__channel__idx")
    readonly_fields = (
        "lead",
        "conversion_action_id",
        "conversion_action_label",
        "conversion_time",
        "conversion_value",
        "currency_code",
        "gclid",
        "hashed_email",
        "imported_at",
        "attempt_count",
        "created_at",
        "modified_at",
    )
    actions = ("retry_failed",)

    @admin.action(description="Reset selected rows to PENDING for the next worker run")
    def retry_failed(self, request, queryset):
        # One UPDATE not N. queue_service.reset_to_pending also logs per row;
        # we log the bulk action here so the audit trail captures the actor + count.
        count = queryset.update(status=OfflineConversionQueue.Status.PENDING, error_message="", imported_at=None)
        logger.info("Bulk reset %s OfflineConversionQueue rows to PENDING by admin %s", count, request.user.username)
