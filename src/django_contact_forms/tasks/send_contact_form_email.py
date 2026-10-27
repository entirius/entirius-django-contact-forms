# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Async dispatch of generic contact-form notification emails.

Since 2.1.0 the render+send is delegated to django-email's
``ContactFormSubmissionEmail`` service subclass, which handles language
activation, per-channel branding, translated template rendering, and SMTP
dispatch in one place. This task is the thin Celery wrapper around it.

Language policy: admin notifications render in the channel's default
language (internal operator comms). Template strings and branding come
from django-email's translation catalog + ``LangChannelConfig``.

Backward-compatible signature: pre-2.1.0 callers pass ``template_html_path``
/ ``subject`` / ``extra_context``; those are accepted-and-logged (warn-and-drop)
so stragglers in the Celery queue from an old deployment are visible.
Booking notifications go through ``booking_notification_service`` directly
and no longer enqueue this task.
"""

from celery import shared_task
from django.apps import apps
from django.core.exceptions import ObjectDoesNotExist
from django.db.utils import ProgrammingError
from django_utils.api.exceptions import BadRequest
from process_logger import ProcessLogger

from django_contact_forms.models import ContactForm, ContactFormAttachment
from django_contact_forms.utils.email_body import body_rows, body_text


def _channel_default_language(channel) -> str | None:
    """Return channel.default_language.iso2 or None. Mirrors django-email's
    ``resolve_email_language(None, channel)`` but without importing the helper
    here (django-email is optional at this layer)."""
    if channel.default_language and channel.default_language.iso2:
        return channel.default_language.iso2
    return None


def _contact_form_language(contact_form) -> str | None:
    """Submitter's language for the client copy, falling back to the channel
    default. Admin notifications use the channel default (operator comms);
    the client copy speaks the visitor's language."""
    if contact_form.language and contact_form.language.iso2:
        return contact_form.language.iso2
    return _channel_default_language(contact_form.channel)


def _submission_context(contact_form) -> dict:
    """Template context shared by the admin notification and the client copy.

    ``form_body`` is the submission as readable text — one ``Label: value``
    line per field, multi-line values kept — because django-email's stock
    templates print it inside ``<pre>``. ``form_body_rows`` carries the same
    fields as ``BodyRow`` objects for templates that render a table.
    ``form_id`` feeds the ``<contact_form_id>`` subject token in django-email.
    """
    return {
        "form_id": contact_form.id,
        "form_email": contact_form.email,
        "form_slug": contact_form.slug or "",
        "form_type": contact_form.type or "",
        "form_code": contact_form.code or "",
        "form_body": body_text(contact_form.body),
        "form_body_rows": body_rows(contact_form.body),
    }


@shared_task(queue="contact_forms")
def send_contact_form_email(
    contact_form_pk,
    admin_email,
    attachments_pk_list=None,
    *,
    send_admin=True,
    send_client_copy=False,
    **_legacy_kwargs,
):
    """Dispatch contact-form emails via django-email.

    ``send_admin`` sends the operator notification to ``admin_email``;
    ``send_client_copy`` additionally sends a confirmation copy to the submitter.
    Pre-2.1.0 callers used ``template_html_path=...``, ``subject=...``,
    ``extra_context=...`` — accepted via ``**_legacy_kwargs``, logged, dropped.
    """
    logger = ProcessLogger("DJANGO_FORMS - send_contact_form_email")
    if _legacy_kwargs:
        logger.warning(f"Ignoring pre-2.1.0 kwargs: {sorted(_legacy_kwargs)}")

    try:
        contact_form = ContactForm.objects.select_related("channel", "channel__default_language", "language").get(
            pk=contact_form_pk
        )
    except ObjectDoesNotExist as e:
        logger.exception(e)
        logger.set_code(4003)
        raise BadRequest("4003") from e

    if not apps.is_installed("django_email"):
        logger.warning("django-email not installed; contact-form email skipped.")
        return

    attachments = list(ContactFormAttachment.objects.filter(pk__in=attachments_pk_list or []))

    submission_context = _submission_context(contact_form)

    if send_admin:
        _send_admin_notification(logger, contact_form, admin_email, submission_context, attachments)

    if send_client_copy and contact_form.email:
        _send_client_copy(logger, contact_form, submission_context, attachments)


def _send_admin_notification(logger, contact_form, admin_email, submission_context, attachments):
    try:
        from django_email.service.contact_forms.contact_form_submission import ContactFormSubmissionEmail
    except (ImportError, ProgrammingError) as exc:
        logger.warning(f"django-email admin dispatch unavailable: {type(exc).__name__}")
        return
    try:
        ContactFormSubmissionEmail(
            language=_channel_default_language(contact_form.channel),
            channel_idx=contact_form.channel.idx,
        ).send(email=[admin_email], submission_context=submission_context, attachment_rows=attachments)
    except Exception as exc:
        logger.set_code(4010)
        logger.exception(exc)


def _send_client_copy(logger, contact_form, submission_context, attachments):
    try:
        from django_email.service.contact_forms.contact_form_client_copy import ContactFormClientCopyEmail
    except (ImportError, ProgrammingError) as exc:
        logger.warning(f"django-email client-copy dispatch unavailable: {type(exc).__name__}")
        return
    try:
        ContactFormClientCopyEmail(
            language=_contact_form_language(contact_form),
            channel_idx=contact_form.channel.idx,
        ).send(
            email=[contact_form.email],
            submission_context=submission_context,
            attachment_rows=attachments,
        )
    except Exception as exc:
        logger.set_code(4011)
        logger.exception(exc)
