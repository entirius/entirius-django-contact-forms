# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Multilang booking notification behaviour.

Covers the change landed in 2.1.0:
- ``BookingRequest.language`` flows into ``ContactForm.language`` FK.
- Booker confirmation renders in the booker's language; admin renders in
  channel default.
- Unknown / missing language falls back silently (no 400).
- ``_build_domain_attachments``-equivalent (now inside django-email) skips
  broken rows; no helper in django-contact-forms anymore.
"""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest
from rest_framework.test import APIClient

from django_contact_forms.services import booking_service
from tests.factories import (
    APIKeyFactory,  # noqa: F401 — parity with neighbour test file
    BookingConfigFactory,
    ChannelFactory,
    enable_global_settings,
)


def _tomorrow_weekday():
    tz = ZoneInfo("Europe/Warsaw")
    candidate = datetime.now(tz) + timedelta(days=2)
    while candidate.weekday() >= 5:
        candidate += timedelta(days=1)
    return candidate


def _setup():
    enable_global_settings(bookings=True)
    channel = ChannelFactory()
    BookingConfigFactory(channel=channel)
    return channel


# ---------------------------------------------------------------------------
# _resolve_language (booking_service) — unknown/empty/unknown-case handling
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_resolve_language_none_returns_none():
    """Silent fallback: empty / None iso2 → no Language row looked up."""
    assert booking_service._resolve_language(None) is None
    assert booking_service._resolve_language("") is None


@pytest.mark.django_db
def test_resolve_language_unknown_iso_returns_none():
    """Unknown ISO code → None (not 400; not exception). Channel default takes over downstream."""
    assert booking_service._resolve_language("xx") is None


@pytest.mark.django_db
def test_resolve_language_uppercase_resolved_case_insensitive():
    """``PL`` and ``pl`` both hit the same Language row (iso2__iexact)."""
    from django_regional.models import Language

    Language.objects.get_or_create(iso2="pl", defaults={"iso3": "pol", "name_en": "Polish", "name_pl": "Polski"})

    resolved = booking_service._resolve_language("PL")
    assert resolved is not None
    assert resolved.iso2 == "pl"


# ---------------------------------------------------------------------------
# ContactForm.language persisted from booking POST
# ---------------------------------------------------------------------------


def _post(client, channel_idx, when, language):
    payload = {
        "booking_date": when.date().isoformat(),
        "booking_time": "10:00",
        "name": "Jan Kowalski",
        "email": "jan@example.com",
        "phone": "+48123456789",
        "language": language,
    }
    return client.post(f"/api/contact-forms/v2/{channel_idx}/bookings/", payload, format="json")


@pytest.mark.django_db
def test_booking_post_persists_language_fk_pl():
    """POST with language=pl → ContactForm.language.iso2 == 'pl'."""
    from django_regional.models import Language

    from django_contact_forms.models import APIKey, ContactForm
    from django_contact_forms.services.calendar.backends.base import BackendEventResult

    Language.objects.get_or_create(iso2="pl", defaults={"iso3": "pol", "name_en": "Polish", "name_pl": "Polski"})

    channel = _setup()
    raw_key = "raw-key-pl"
    APIKey.objects.create(channel=channel, key=raw_key, scope=APIKey.Scope.BOOKING)
    client = APIClient()
    client.credentials(HTTP_X_API_KEY=raw_key)

    backend = MagicMock()
    backend.is_slot_free.return_value = True
    backend.create_event.return_value = BackendEventResult(event_id="e", meet_link="")

    with (
        patch("django_contact_forms.services.booking_service.get_calendar_backend", return_value=backend),
        # Silence the email dispatch — subject of another test.
        patch("django_email.service.contact_forms.booking_confirmation.BookingConfirmationEmail"),
        patch("django_email.service.contact_forms.booking_admin_notification.BookingAdminNotificationEmail"),
    ):
        resp = _post(client, channel.idx, _tomorrow_weekday(), "pl")

    assert resp.status_code == 201, resp.json()
    cf = ContactForm.objects.get(pk=resp.json()["contact_form_id"])
    assert cf.language is not None
    assert cf.language.iso2 == "pl"


@pytest.mark.django_db
def test_booking_post_with_unknown_language_leaves_null():
    """Unknown iso2 on POST → ContactForm.language stays None; no crash."""
    from django_contact_forms.models import APIKey, ContactForm
    from django_contact_forms.services.calendar.backends.base import BackendEventResult

    channel = _setup()
    raw_key = "raw-key-xx"
    APIKey.objects.create(channel=channel, key=raw_key, scope=APIKey.Scope.BOOKING)
    client = APIClient()
    client.credentials(HTTP_X_API_KEY=raw_key)

    backend = MagicMock()
    backend.is_slot_free.return_value = True
    backend.create_event.return_value = BackendEventResult(event_id="e", meet_link="")

    with (
        patch("django_contact_forms.services.booking_service.get_calendar_backend", return_value=backend),
        patch("django_email.service.contact_forms.booking_confirmation.BookingConfirmationEmail"),
        patch("django_email.service.contact_forms.booking_admin_notification.BookingAdminNotificationEmail"),
    ):
        resp = _post(client, channel.idx, _tomorrow_weekday(), "xx")

    assert resp.status_code == 201, resp.json()
    cf = ContactForm.objects.get(pk=resp.json()["contact_form_id"])
    assert cf.language is None


# ---------------------------------------------------------------------------
# Booker lang vs admin lang propagation into EmailService subclasses
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_booker_lang_wins_admin_uses_channel_default():
    """Booker email instantiated with booker.language.iso2; admin with channel.default_language.iso2."""
    from django_regional.models import Language

    from django_contact_forms.models import APIKey
    from django_contact_forms.services.calendar.backends.base import BackendEventResult

    pl, _ = Language.objects.get_or_create(
        iso2="pl", defaults={"iso3": "pol", "name_en": "Polish", "name_pl": "Polski"}
    )
    en, _ = Language.objects.get_or_create(
        iso2="en", defaults={"iso3": "eng", "name_en": "English", "name_pl": "Angielski"}
    )

    channel = _setup()
    channel.default_language = en
    channel.save()
    raw_key = "raw-key-mix"
    APIKey.objects.create(channel=channel, key=raw_key, scope=APIKey.Scope.BOOKING)
    client = APIClient()
    client.credentials(HTTP_X_API_KEY=raw_key)

    backend = MagicMock()
    backend.is_slot_free.return_value = True
    backend.create_event.return_value = BackendEventResult(event_id="e", meet_link="")

    with (
        patch("django_contact_forms.services.booking_service.get_calendar_backend", return_value=backend),
        patch("django_email.service.contact_forms.booking_confirmation.BookingConfirmationEmail") as confirm_cls,
        patch(
            "django_email.service.contact_forms.booking_admin_notification.BookingAdminNotificationEmail"
        ) as admin_cls,
    ):
        _post(client, channel.idx, _tomorrow_weekday(), "pl")

    # Booker: language="pl" (booker's request)
    assert confirm_cls.call_args.kwargs["language"] == "pl"
    # Admin: language="en" (channel default)
    assert admin_cls.call_args.kwargs["language"] == "en"


# ---------------------------------------------------------------------------
# Degradation path — django-email unavailable → silent skip
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_send_booking_notifications_silent_skip_on_importerror():
    """If ``django_email.language`` can't be imported, the service logs a warning
    and returns. Booking still completes, no exception bubbles up."""
    from django_contact_forms.services import booking_notification_service

    # The three imports inside the service are re-evaluated on every call,
    # so sys.modules manipulation is enough to simulate absence.
    channel = _setup()
    cf = MagicMock()
    cf.email = "jan@example.com"
    cf.body = {}
    cf.language = None
    booking = MagicMock(timezone="Europe/Warsaw")
    result = MagicMock(contact_form=cf, booking=booking)

    with patch.dict("sys.modules", {"django_email.language": None}):
        # No raise — silent skip
        booking_notification_service.send_booking_notifications(channel=channel, result=result)
