# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from django.db import models

from django_contact_forms.models.base_model import BaseModel
from django_contact_forms.utils.encrypted_field import EncryptedTextField


class GoogleAdsConfig(BaseModel):
    """Per-channel Google Ads credentials + conversion-action mapping.

    One row per channel (OneToOne). Refresh token is encrypted at rest. Conversion
    action IDs are per-channel because each shop typically has its own Ads account.
    """

    channel = models.OneToOneField("Channel", on_delete=models.CASCADE, related_name="google_ads_config")
    enabled = models.BooleanField(
        default=False,
        help_text="Channel-level enable. Must also satisfy the global ContactFormsSettings.google_ads_enabled toggle.",
    )
    customer_id = models.CharField(
        max_length=16, blank=True, default="", help_text="Google Ads account ID, digits only (e.g. 8323936346)."
    )
    login_customer_id = models.CharField(
        max_length=16, blank=True, default="", help_text="Optional MCC ID when accessing via manager account."
    )
    oauth_refresh_token = EncryptedTextField(
        blank=True, default="", help_text="OAuth2 refresh token (encrypted at rest)."
    )
    default_currency_code = models.CharField(max_length=3, default="EUR")

    # Conversion-action ID mapping (per Lead status)
    meeting_booked_action_id = models.CharField(max_length=32, blank=True, default="")
    qualified_lead_action_id = models.CharField(max_length=32, blank=True, default="")
    won_deal_action_id = models.CharField(max_length=32, blank=True, default="")

    # Static conversion values (won uses Lead.deal_value)
    meeting_booked_value = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    qualified_lead_value = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    class Meta:
        verbose_name = "Google Ads config"
        verbose_name_plural = "Google Ads configs"

    def __str__(self) -> str:
        return f"GoogleAdsConfig(channel={self.channel.idx}, enabled={self.enabled})"
