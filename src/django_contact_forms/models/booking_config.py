# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from pathlib import Path

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator
from django.db import models

from django_contact_forms import settings as cf_settings
from django_contact_forms.models.base_model import BaseModel


class BookingConfig(BaseModel):
    """Per-channel calendar booking configuration. One row per channel (OneToOne)."""

    class Provider(models.TextChoices):
        GOOGLE_CALENDAR = "google_calendar", "Google Calendar"
        LOCAL = "local", "Local (no external calendar)"

    channel = models.OneToOneField(
        "Channel", on_delete=models.CASCADE, related_name="booking_config", primary_key=False
    )
    enabled = models.BooleanField(default=False)
    provider = models.CharField(
        max_length=32,
        choices=Provider.choices,
        default=Provider.GOOGLE_CALENDAR,
        help_text=(
            "Calendar backend. 'google_calendar' requires the [bookings] extra + "
            "service-account credentials; 'local' is DB-only and needs no external "
            "setup. See docs/volkanos/modules/contact-forms/bookings."
        ),
    )

    # Google Calendar — service account + domain-wide delegation
    service_account_credentials_path = models.CharField(
        max_length=512,
        blank=True,
        default="",
        help_text=(
            "Absolute path inside the container to the service-account JSON key. "
            "Validated against CONTACT_FORMS_CREDENTIALS_DIR (default /app/credentials/) — "
            "must be a real .json file under that directory, no symlinks."
        ),
    )
    impersonate_email = models.EmailField(
        blank=True,
        default="",
        help_text="Email of the real user the service account acts as (events created on their primary).",
    )
    calendar_id = models.CharField(
        max_length=255,
        blank=True,
        default="primary",
        help_text="Shared calendar ID for free-busy queries; 'primary' for impersonated user only.",
    )

    # Slot rules — working hours come from related BookingTimeWindow rows (≥1 per config).
    slot_duration_minutes = models.PositiveIntegerField(default=30)
    days_ahead = models.PositiveIntegerField(default=14)
    weekdays_only = models.BooleanField(default=True)
    timezone = models.CharField(max_length=64, default="Europe/Warsaw")

    # Event template
    event_summary_template = models.CharField(
        max_length=255, default="Booking - {name}", help_text="Use {name} as a placeholder for the booker's name."
    )

    # FOMO synthetic-busy slots — purely cosmetic, makes the calendar look more
    # occupied than it is. Never affects actual booking creation (is_slot_free
    # consults only the real backend). See services/calendar/fomo.py.
    fomo_enabled = models.BooleanField(
        default=False,
        help_text=(
            "Master toggle for synthetic busy slots ('fake-booked' time blocks shown to visitors "
            "to combat empty-calendar deterrence). Off = exact real availability is shown."
        ),
    )
    fomo_intensity = models.PositiveIntegerField(
        default=50,
        validators=[MaxValueValidator(100)],
        help_text=(
            "0-100. Apparent fill-up perception. 0 = off, 50 = balanced (~50% peak slots fake-busy), "
            "80 = aggressive. Values >80 are clamped per-day to avoid 'fully booked' deterrence "
            "(visitors abandon when they see no openings)."
        ),
    )
    fomo_blackout_full_days = models.PositiveIntegerField(
        default=1,
        validators=[MaxValueValidator(3)],
        help_text=(
            "Max full-day blackouts within the visible window (today and tomorrow are always "
            "excluded so 'fresh availability' urgency works). 0 = no blackouts."
        ),
    )

    class Meta:
        verbose_name = "Booking config"
        verbose_name_plural = "Booking configs"

    def __str__(self) -> str:
        return f"BookingConfig(channel={self.channel.idx}, enabled={self.enabled})"

    def clean(self) -> None:
        """Defend against path traversal / file disclosure via the credentials_path field.

        The admin sets this string. Without validation, an admin (or compromised
        admin session) could point at /etc/passwd, /proc/self/environ, another
        tenant's SA JSON, or a planted symlink, and the calendar backend would
        try to open it. The downstream SDK error then echoes the parse failure
        back to the API caller (file disclosure).
        """
        super().clean()
        path = (self.service_account_credentials_path or "").strip()
        if not path:
            return  # empty is fine — backend init will fail elsewhere with a clear message

        if not path.endswith(".json"):
            raise ValidationError({"service_account_credentials_path": "Must end in .json"})

        try:
            resolved = Path(path).resolve(strict=False)
        except (OSError, RuntimeError) as exc:
            raise ValidationError({"service_account_credentials_path": f"Invalid path: {exc}"}) from exc

        creds_root = Path(cf_settings.CONTACT_FORMS_CREDENTIALS_DIR).resolve(strict=False)
        try:
            resolved.relative_to(creds_root)
        except ValueError as exc:
            raise ValidationError(
                {
                    "service_account_credentials_path": (
                        f"Path must resolve under CONTACT_FORMS_CREDENTIALS_DIR ({creds_root})"
                    )
                }
            ) from exc

        # Refuse symlinks even if they point inside the dir — they can be re-pointed.
        if Path(path).is_symlink() or resolved != Path(path).resolve(strict=False):
            # The second check catches the case where the original path itself
            # contained a symlink component anywhere up the chain.
            if Path(path).is_symlink():
                raise ValidationError({"service_account_credentials_path": "Symlinks are not allowed"})
