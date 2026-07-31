# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Singleton runtime settings (one row, pk=1). PimSettings/MatrixSettings pattern."""

from django.core.cache import cache
from django.db import models

CACHE_KEY = "contact_forms:settings"
CACHE_TTL = 60


class ContactFormsSettings(models.Model):
    """Master kill-switches for optional features. Managed via Django admin."""

    bookings_enabled = models.BooleanField(
        default=False, help_text="Enable the public booking endpoint and BookingConfig per-channel rows."
    )
    google_ads_enabled = models.BooleanField(
        default=False, help_text="Enable Lead status → Google Ads offline conversion enqueue + worker."
    )

    class Meta:
        verbose_name = "Contact Forms settings"
        verbose_name_plural = "Contact Forms settings"

    def __str__(self) -> str:
        return "Contact Forms settings"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)
        cache.delete(CACHE_KEY)

    @classmethod
    def load(cls) -> "ContactFormsSettings":
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


def _load_cached() -> dict[str, bool]:
    """Single get_or_create per cold cache, both flags returned together.

    Was: two helpers each calling load() → two get_or_create queries on cold start.
    Now: one DB hit, one cache entry.
    """
    cached = cache.get(CACHE_KEY)
    if cached is not None:
        return cached
    obj = ContactFormsSettings.load()
    data = {"bookings_enabled": obj.bookings_enabled, "google_ads_enabled": obj.google_ads_enabled}
    cache.set(CACHE_KEY, data, CACHE_TTL)
    return data


def is_bookings_enabled() -> bool:
    return _load_cached()["bookings_enabled"]


def is_google_ads_enabled() -> bool:
    return _load_cached()["google_ads_enabled"]
