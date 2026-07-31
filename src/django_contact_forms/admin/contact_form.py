# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from django.contrib import admin

from django_contact_forms.models import ContactForm, ContactFormAttachment


class ContactFormAttachmentTabularAdmin(admin.TabularInline):
    model = ContactFormAttachment
    fields = ["name", "attachment"]
    extra = 0


@admin.register(ContactForm)
class ContactFormAdmin(admin.ModelAdmin):
    model = ContactForm
    list_display = ["id", "email", "channel", "language", "created_at", "slug", "code", "type", "created_at"]
    search_fields = ["id", "email", "code", "type"]
    list_filter = ("language", "slug", "channel__idx")
    ordering = ["-created_at"]
    inlines = [ContactFormAttachmentTabularAdmin]


@admin.register(ContactFormAttachment)
class ContactFormAttachmentAdmin(admin.ModelAdmin):
    model = ContactFormAttachment
    list_display = ["id", "name", "contact_form", "created_at"]
    search_fields = ["id", "name"]
    ordering = ["-created_at"]
    list_filter = ("contact_form__channel__idx", "contact_form__language", "contact_form__slug")

    def get_readonly_fields(self, request, obj=None):
        if obj:
            return ["name", "contact_form"]
        return []
