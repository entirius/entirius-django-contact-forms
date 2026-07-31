# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from typing import TYPE_CHECKING

from django.db import models

from django_contact_forms.models.base_model import BaseModel

if TYPE_CHECKING:
    from django_contact_forms.models.channel import Channel


class FormType(BaseModel):
    """Channel-scoped catalog of allowed form types.

    Seeded per project via fixtures (e.g. general/product/default). The submit
    pipeline resolves an incoming type against this catalog and falls back to the
    channel's ``is_default`` row when the value is empty or unknown. Replaces the
    previous free-string ``ContactForm.type`` reality where the column was always
    empty for storefront traffic.
    """

    channel: "Channel" = models.ForeignKey("Channel", on_delete=models.CASCADE, related_name="form_types")
    code = models.CharField(max_length=256)
    label = models.CharField(max_length=256, blank=True, default="")
    is_default = models.BooleanField(
        default=False,
        help_text="Used when a submission carries no type or an unknown one. One per channel.",
    )
    objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["channel", "code"],
                name="unique_channel_form_type_code",
            ),
            models.UniqueConstraint(
                fields=["channel"],
                condition=models.Q(is_default=True),
                name="unique_default_form_type_per_channel",
            ),
        ]
        ordering = []
        verbose_name = "form type"
        verbose_name_plural = "form types"

    def __str__(self):
        marker = " *" if self.is_default else ""
        return f"FormType({self.channel.idx}:{self.code}{marker})"
