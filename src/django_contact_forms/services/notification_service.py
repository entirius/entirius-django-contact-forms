# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Business logic for email notification configuration and dispatch."""

from dataclasses import dataclass

from celery import current_app
from django.db.models import QuerySet
from process_logger import ProcessLogger

from django_contact_forms import settings
from django_contact_forms.models import Channel, FormNotificationConfig
from django_contact_forms.tasks.send_contact_form_email import send_contact_form_email

logger = ProcessLogger(process_name="notification_dispatch", module="django_contact_forms")


@dataclass(frozen=True)
class EmailDispatchDecision:
    """Outcome of resolving a submission against the notification config chain."""

    send_admin: bool
    recipient: str | None
    send_client_copy: bool


def _resolve_config(channel: Channel, form_type: str | None, slug: str | None) -> FormNotificationConfig | None:
    """Walk the fallback chain and return the matching config (or None).

    1. exact(channel, type, slug)
    2. type-level(channel, type, "")
    3. channel-level(channel, "", "")
    """
    form_type = form_type or ""
    slug = slug or ""

    if form_type and slug:
        config = _find_config(channel, form_type, slug)
        if config:
            return config
    if form_type:
        config = _find_config(channel, form_type, "")
        if config:
            return config
    return _find_config(channel, "", "")


def should_send_email(
    channel: Channel, form_type: str | None = None, slug: str | None = None
) -> tuple[bool, str | None]:
    """Determine whether to send the admin email and to whom.

    Falls back to the global ``CONTACT_FORM_SEND_ADMIN_EMAIL`` setting when no
    config matches. Returns (should_send, recipient_email_or_none).
    """
    config = _resolve_config(channel, form_type, slug)
    if config:
        return config.send_email, config.recipient_email or None
    return settings.CONTACT_FORM_SEND_ADMIN_EMAIL, None


def should_send_client_copy(channel: Channel, form_type: str | None = None, slug: str | None = None) -> bool:
    """Whether the submitter receives a copy, per the matching config.

    Falls back to the global ``CONTACT_FORM_SEND_CLIENT_COPY`` setting when no
    config matches. The caller additionally gates on ``body.send_copy``.
    """
    config = _resolve_config(channel, form_type, slug)
    if config:
        return config.send_client_copy
    return settings.CONTACT_FORM_SEND_CLIENT_COPY


def resolve_email_dispatch(
    channel: Channel, form_type: str | None = None, slug: str | None = None
) -> EmailDispatchDecision:
    """Resolve admin + client-copy decisions in a single config-chain walk.

    Preferred entry point for the submit path — avoids resolving the same
    ``(channel, form_type, slug)`` twice via ``should_send_email`` +
    ``should_send_client_copy``. The caller still gates the client copy on
    ``body.send_copy`` and a non-empty submitter email.
    """
    config = _resolve_config(channel, form_type, slug)
    if config:
        return EmailDispatchDecision(
            send_admin=config.send_email,
            recipient=config.recipient_email or None,
            send_client_copy=config.send_client_copy,
        )
    return EmailDispatchDecision(
        send_admin=settings.CONTACT_FORM_SEND_ADMIN_EMAIL,
        recipient=None,
        send_client_copy=settings.CONTACT_FORM_SEND_CLIENT_COPY,
    )


def _find_config(channel: Channel, form_type: str, slug: str) -> FormNotificationConfig | None:
    return FormNotificationConfig.objects.filter(channel=channel, form_type=form_type, slug=slug).first()


def dispatch_email(
    contact_form_pk: str,
    recipient_email: str,
    attachments_pk_list: list[int] | None = None,
    *,
    send_admin: bool = True,
    send_client_copy: bool = False,
    template_html_path: str | None = None,
    subject: str | None = None,
    extra_context: dict | None = None,
) -> None:
    """Dispatch email via Celery queue or synchronous fallback.

    ``send_admin`` / ``send_client_copy`` toggle the two recipients the task can
    serve (admin notification + submitter copy); at least one is expected to be
    true. The optional template/subject/context kwargs are legacy overrides kept
    for pre-2.1.0 enqueued tasks. All extras default to absent so the common
    plain-submit case keeps the AMQP payload minimal.
    """
    attachments_pk_list = attachments_pk_list or []
    kwargs: dict = {}
    if not send_admin:
        kwargs["send_admin"] = False
    if send_client_copy:
        kwargs["send_client_copy"] = True
    if template_html_path is not None:
        kwargs["template_html_path"] = template_html_path
    if subject is not None:
        kwargs["subject"] = subject
    if extra_context is not None:
        kwargs["extra_context"] = extra_context

    if "contact_forms" in current_app.amqp.queues:
        try:
            send_contact_form_email.apply_async(
                args=[contact_form_pk, recipient_email, attachments_pk_list],
                kwargs=kwargs,
                queue="contact_forms",
            )
            return
        except Exception as exc:
            logger.exception(exc)

    send_contact_form_email(contact_form_pk, recipient_email, attachments_pk_list, **kwargs)


def list_configs(*, channel_idx: str | None = None) -> QuerySet[FormNotificationConfig]:
    qs = FormNotificationConfig.objects.select_related("channel").order_by("channel__idx", "form_type", "slug")
    if channel_idx:
        qs = qs.filter(channel__idx=channel_idx)
    return qs


def get_config(*, pk: int) -> FormNotificationConfig:
    return FormNotificationConfig.objects.select_related("channel").get(pk=pk)


def create_config(
    *,
    channel_id: int,
    form_type: str,
    slug: str,
    send_email: bool,
    recipient_email: str | None,
    send_client_copy: bool = False,
) -> FormNotificationConfig:
    channel = Channel.objects.get(pk=channel_id)
    return FormNotificationConfig.objects.create(
        channel=channel,
        form_type=form_type,
        slug=slug,
        send_email=send_email,
        send_client_copy=send_client_copy,
        recipient_email=recipient_email,
    )


_EDITABLE_CONFIG_FIELDS = frozenset({"form_type", "slug", "send_email", "send_client_copy", "recipient_email"})


def update_config(*, pk: int, updates: dict) -> FormNotificationConfig:
    invalid = set(updates) - _EDITABLE_CONFIG_FIELDS
    if invalid:
        raise ValueError(f"Fields not editable via update_config: {sorted(invalid)}")
    config = FormNotificationConfig.objects.select_related("channel").get(pk=pk)
    for field, value in updates.items():
        setattr(config, field, value)
    config.save()
    return config


def delete_config(*, pk: int) -> None:
    FormNotificationConfig.objects.get(pk=pk).delete()
