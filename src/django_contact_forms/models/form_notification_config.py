# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from typing import TYPE_CHECKING

from django.db import models

from django_contact_forms.models.base_model import BaseModel

if TYPE_CHECKING:
    from django_contact_forms.models.channel import Channel


class FormNotificationConfig(BaseModel):
    """Per form type/slug email notification configuration.

    Fallback chain: exact(channel, type, slug) -> type-level(channel, type, "") -> channel-level(channel, "", "") -> global CONTACT_FORM_SEND_ADMIN_EMAIL.
    """

    channel: "Channel" = models.ForeignKey("Channel", on_delete=models.CASCADE)
    form_type = models.CharField(max_length=256, blank=True, default="")
    slug = models.CharField(max_length=256, blank=True, default="")
    send_email = models.BooleanField(default=True)
    send_client_copy = models.BooleanField(
        default=False,
        help_text="Whether the submitter receives a copy email (gated additionally by body.send_copy).",
    )
    recipient_email = models.EmailField(blank=True, default="")
    objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["channel", "form_type", "slug"],
                name="unique_channel_form_type_slug",
            ),
        ]
        ordering = []
        verbose_name = "form notification config"
        verbose_name_plural = "form notification configs"

    def __str__(self):
        parts = [f"channel={self.channel.idx}"]
        if self.form_type:
            parts.append(f"type={self.form_type}")
        if self.slug:
            parts.append(f"slug={self.slug}")
        return f"NotificationConfig({', '.join(parts)})"
