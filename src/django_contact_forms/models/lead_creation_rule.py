# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from typing import TYPE_CHECKING

from django.db import models

from django_contact_forms.models.base_model import BaseModel
from django_contact_forms.models.lead import Lead

if TYPE_CHECKING:
    from django_contact_forms.models.channel import Channel


class LeadCreationRule(BaseModel):
    """Per form type/slug opt-in rule for auto-creating a Lead on public submit.

    Parallel to FormNotificationConfig but for lead pipeline instead of email
    routing. Fallback chain: exact(channel, type, slug) -> type-level(channel,
    type, "") -> channel-level(channel, "", "") -> off (no global default —
    Lead creation is opt-in only, never accidental).

    Disabled rows (`enabled=False`) block lookup from falling through to a
    coarser match, so an operator can disable a specific form without tearing
    down the parent channel-level rule.
    """

    channel: "Channel" = models.ForeignKey("Channel", on_delete=models.CASCADE)
    form_type = models.CharField(max_length=256, blank=True, default="")
    slug = models.CharField(max_length=256, blank=True, default="")
    enabled = models.BooleanField(default=True)
    source_type = models.CharField(
        max_length=16,
        choices=Lead.SourceType.choices,
        default=Lead.SourceType.FORM,
        help_text="Value written to Lead.source_type when this rule fires.",
    )
    objects = models.Manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["channel", "form_type", "slug"],
                name="unique_lead_rule_channel_type_slug",
            ),
        ]
        ordering = []
        verbose_name = "lead creation rule"
        verbose_name_plural = "lead creation rules"

    def __str__(self):
        parts = [f"channel={self.channel.idx}"]
        if self.form_type:
            parts.append(f"type={self.form_type}")
        if self.slug:
            parts.append(f"slug={self.slug}")
        parts.append(f"enabled={self.enabled}")
        return f"LeadCreationRule({', '.join(parts)})"
