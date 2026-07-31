# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from django.db import models


class ContactFormAttachmentManager(models.Manager):
    def get_size_all_attachments_MB(self, contact_form):
        size_sum_form = 0
        for form in self.filter(contact_form=contact_form):
            size_sum_form += form.attachment.size
        return size_sum_form / 1024 / 1024
