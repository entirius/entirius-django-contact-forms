# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from time import time

from django.core.files.storage import FileSystemStorage
from django.db import models

from django_contact_forms import settings
from django_contact_forms.models import ContactForm
from django_contact_forms.models.base_model import BaseModel
from django_contact_forms.models.managers.contact_form_attachment import ContactFormAttachmentManager
from django_contact_forms.settings import FORMS_MAX_ATTACHMENT_COUNT, FORMS_MAX_ATTACHMENT_MB_SIZE
from django_contact_forms.utils.exceptions import AttachmentCountLimitReached, AttachmentSizeLimitReached


def contact_form_attachment_directory_path(instance, filename):
    filename = str(int(time())) + "-" + filename
    return f"{instance.contact_form.id}/{filename}"


def contact_form_storage():
    return FileSystemStorage(location=settings.CUSTOM_FORM_ATTACHMENT_DIR)


class ContactFormAttachment(BaseModel):
    name = models.CharField(  # noqa: DJ001
        max_length=256,
        blank=True,
        null=True,
        help_text="It will automatically be filled in with the file name when saving",
    )
    contact_form: "ContactForm" = models.ForeignKey("ContactForm", null=False, blank=False, on_delete=models.PROTECT)
    attachment = models.FileField(
        blank=False, null=False, upload_to=contact_form_attachment_directory_path, storage=contact_form_storage
    )
    objects = ContactFormAttachmentManager()

    def save(self, *args, **kwargs):
        attachments_size = ContactFormAttachment.objects.get_size_all_attachments_MB(self.contact_form) + (
            self.attachment.size / 1024 / 1024
        )
        attachments_count = ContactFormAttachment.objects.filter(contact_form=self.contact_form).count() + 1

        if attachments_size > FORMS_MAX_ATTACHMENT_MB_SIZE:
            raise AttachmentSizeLimitReached(
                f"Files size is too large. Maximum size is {settings.FORMS_MAX_ATTACHMENT_MB_SIZE} MB."
            )

        if attachments_count > FORMS_MAX_ATTACHMENT_COUNT:
            raise AttachmentCountLimitReached(
                f"Files count is too large. Maximum count is {settings.FORMS_MAX_ATTACHMENT_COUNT}."
            )

        if self.attachment and hasattr(self.attachment, "name"):
            self.name = self.attachment.name

        super().save(*args, **kwargs)
