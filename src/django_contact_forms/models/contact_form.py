# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import json
import random
import string
from typing import TYPE_CHECKING

from django.db import models

from django_contact_forms import settings
from django_contact_forms.models.base_model import BaseModel
from django_contact_forms.utils.exceptions import JSONTooLargeException

if TYPE_CHECKING:
    from django_contact_forms.models import Channel


class ContactForm(BaseModel):
    class Status(models.TextChoices):
        TODO = "todo", "To Do"
        IN_PROGRESS = "in_progress", "In Progress"
        DONE = "done", "Done"

    id = models.CharField(max_length=12, unique=True, primary_key=True, default=None)
    slug = models.CharField(max_length=256, null=True, blank=True)  # noqa: DJ001
    email = models.EmailField(null=False, blank=False)
    channel: "Channel" = models.ForeignKey("Channel", on_delete=models.CASCADE)
    language = models.ForeignKey("django_regional.Language", on_delete=models.SET_NULL, blank=True, null=True)
    body = models.JSONField(blank=True, null=True)
    type = models.CharField(max_length=256, null=True, blank=True)  # noqa: DJ001
    code = models.CharField(max_length=256, null=True, blank=True)  # noqa: DJ001
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.TODO)
    objects = models.Manager()

    def id_generator(self, size=12, chars=string.digits):
        return "".join(random.choice(chars) for _ in range(size))  # noqa: S311 — non-crypto 12-digit PK generator

    def save(self, *args, **kwargs):
        if self.body:
            body_as_json = json.dumps(self.body)
            if len(body_as_json) / 1024 / 1024 > settings.FORMS_MAX_JSON_MB_SIZE:
                raise JSONTooLargeException(
                    f"JSON data is too large. Maximum size is {settings.FORMS_MAX_JSON_MB_SIZE}."
                )

        if not self.id:
            id_cf = self.id_generator()
            while ContactForm.objects.filter(id=id_cf).exists():
                id_cf = self.id_generator()
            self.id = id_cf

        super().save(*args, **kwargs)

    def as_data(self):
        return {
            "id": self.id,
            "email": self.email,
            "channel_idx": self.channel.idx,
            "slug": self.slug,
            "language": self.language.iso2 if self.language else None,
            "body": self.body,
            "code": self.code if self.code else None,
        }

    def __str__(self):
        return f"{self.channel.idx} | {self.id}"

    class Meta:
        ordering = []
        verbose_name_plural = "contact_forms"
