# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from django.db import models
from idx_normalizator import validate_idx

from django_contact_forms.models.base_model import BaseModel


class Channel(BaseModel):
    idx = models.CharField(max_length=128, blank=False, null=False, unique=True)
    label = models.CharField(max_length=128, blank=False, null=False, default="", unique=True)
    default_language = models.ForeignKey(
        "django_regional.Language",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="default_language_forms",
    )
    admin_email = models.EmailField(blank=False, null=False, default="email_administratora_fromularzu@test.pl")
    objects = models.Manager()

    def __str__(self):
        return f"{self.label} [{self.idx}]"

    def save(self, *args, **kwargs):
        validate_idx(str(self.idx))
        super().save(*args, **kwargs)

    class Meta:
        ordering = []
        verbose_name_plural = "channels"
