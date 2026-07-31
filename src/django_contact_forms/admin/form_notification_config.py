# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from django.contrib import admin

from django_contact_forms.models.form_notification_config import FormNotificationConfig


@admin.register(FormNotificationConfig)
class FormNotificationConfigAdmin(admin.ModelAdmin):
    list_display = ["channel", "form_type", "slug", "send_email", "send_client_copy", "recipient_email"]
    list_filter = ["channel__idx", "send_email", "send_client_copy"]
    search_fields = ["form_type", "slug", "recipient_email"]
    ordering = ["channel__idx", "form_type", "slug"]
