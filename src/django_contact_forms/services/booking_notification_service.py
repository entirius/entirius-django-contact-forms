# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Booking notifications via django-email EmailService subclasses.

Two emails are fanned out on a successful booking:

- **Booker confirmation** — always sent. Renders in the booker's language
  (``ContactForm.language``), falling back to the channel's default.
- **Admin notification** — opt-in via ``FormNotificationConfig``. Renders
  in the channel's default language (internal comms — operator-facing).

The dispatch is synchronous and silent-fails: a broker outage or mail
error must never downgrade a successful booking to a 5xx. Errors are
logged with ``ProcessLogger.exception(...)`` so support gets the full
stack for tracing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from process_logger import ProcessLogger

from django_contact_forms.services import notification_service
from django_contact_forms.services.booking_service import FORM_TYPE_BOOKING

if TYPE_CHECKING:
    from django_contact_forms.models import Booking, Channel, ContactForm
    from django_contact_forms.services.booking_service import BookingResult


def _logger() -> ProcessLogger:
    return ProcessLogger("DJANGO_FORMS - send_booking_notifications")


def _booking_context(contact_form: ContactForm, booking: Booking) -> dict:
    body = contact_form.body or {}
    return {
        "booker_name": body.get("name", ""),
        "booker_email": contact_form.email,
        "booker_phone": body.get("phone", ""),
        "booker_company": body.get("company", ""),
        "booker_message": body.get("message", ""),
        "meeting_start": booking.meeting_start,
        "meeting_end": booking.meeting_end,
        "meet_link": booking.meet_link,
        "timezone": booking.timezone,
    }


def send_booking_notifications(*, channel: Channel, result: BookingResult) -> None:
    """Dispatch booker confirmation (always) + admin notification (opt-in)."""
    # Deferred import — django-email is an optional branding backend. Importing
    # at module top would break test suites that run without it installed.
    try:
        from django_email.language import resolve_email_language
        from django_email.service.contact_forms.booking_admin_notification import BookingAdminNotificationEmail
        from django_email.service.contact_forms.booking_confirmation import BookingConfirmationEmail
    except (ImportError, RuntimeError) as exc:
        _logger().warning(f"django-email unavailable: {type(exc).__name__}")
        return

    cf = result.contact_form
    booking = result.booking
    ctx = _booking_context(cf, booking)

    booker_iso2 = cf.language.iso2 if cf.language else None
    booker_lang = resolve_email_language(booker_iso2, channel)
    admin_lang = resolve_email_language(None, channel)

    try:
        BookingConfirmationEmail(language=booker_lang, channel_idx=channel.idx).send(
            email=[cf.email], booking_context=ctx
        )
    except Exception as exc:
        _logger().exception(exc)  # silent-non-re-raise, full stack for support

    should_send, recipient_override = notification_service.should_send_email(channel, form_type=FORM_TYPE_BOOKING)
    if not should_send:
        return
    recipient = recipient_override or channel.admin_email
    try:
        BookingAdminNotificationEmail(language=admin_lang, channel_idx=channel.idx).send(
            email=[recipient], booking_context=ctx
        )
    except Exception as exc:
        _logger().exception(exc)
