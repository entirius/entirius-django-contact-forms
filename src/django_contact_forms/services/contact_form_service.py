# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Business logic for contact form submissions."""

from django.db.models import Q, QuerySet
from process_logger import ProcessLogger

from django_contact_forms import settings
from django_contact_forms.models import (
    Channel,
    ContactForm,
    ContactFormAttachment,
    FormType,
)

logger = ProcessLogger(process_name="contact_form_service", module="django_contact_forms")

_VALID_ORDERINGS = {
    "created_at",
    "-created_at",
    "email",
    "-email",
    "type",
    "-type",
    "status",
    "-status",
}


def list_submissions(
    *,
    channel_idx: str | None = None,
    form_type: str | None = None,
    slug: str | None = None,
    search: str | None = None,
    ordering: str | None = None,
    status: str | None = None,
) -> QuerySet[ContactForm]:
    if ordering and ordering not in _VALID_ORDERINGS:
        raise ValueError(f"Invalid ordering: {ordering}")

    qs = ContactForm.objects.select_related("channel", "language").prefetch_related("contactformattachment_set")

    if channel_idx:
        qs = qs.filter(channel__idx=channel_idx)
    if form_type:
        qs = qs.filter(type__iexact=form_type)
    if slug:
        qs = qs.filter(slug__iexact=slug)
    if status:
        qs = qs.filter(status__iexact=status)
    if search:
        qs = qs.filter(Q(id__icontains=search) | Q(email__icontains=search) | Q(code__icontains=search))

    qs = qs.order_by(ordering if ordering else "-created_at")
    return qs


def get_submission(*, pk: str) -> ContactForm:
    return ContactForm.objects.select_related("channel", "language").get(pk=pk)


def get_channel(*, idx: str) -> Channel:
    return Channel.objects.get(idx=idx)


def list_form_types(*, channel: Channel) -> QuerySet[FormType]:
    return FormType.objects.filter(channel=channel).order_by("code")


def resolve_form_type(
    *,
    channel: Channel,
    form_type: str | None = None,
    type_id: str | None = None,
    body=None,
) -> str:
    """Resolve an incoming submission to a configured form-type code.

    Priority: explicit ``form_type`` field → ``body['form_type']`` → legacy
    ``body['type']`` → URL ``type_id``. The candidate is normalized against the
    channel's FormType catalog; anything empty or unknown falls back to the
    channel's ``is_default`` row, then to ``settings.CONTACT_FORM_DEFAULT_TYPE``.
    Lenient by design — storefronts send arbitrary values; we never raise here.
    """
    candidate = form_type
    if not candidate and isinstance(body, dict):
        candidate = body.get("form_type") or body.get("type")
    if not candidate:
        candidate = type_id

    # One query serves both the membership check and the default lookup. The
    # candidate may be a non-string JSON value (storefronts send arbitrary
    # bodies); only a string can match a code — anything else falls through to
    # the default, never raising (the membership test must not see a non-hashable).
    rows = list(FormType.objects.filter(channel=channel))
    if isinstance(candidate, str) and candidate in {row.code for row in rows}:
        return candidate

    default = next((row for row in rows if row.is_default), None)
    resolved = default.code if default else settings.CONTACT_FORM_DEFAULT_TYPE
    if candidate:
        logger.warning(f"Unknown form_type '{candidate}' for channel '{channel.idx}'; falling back to '{resolved}'.")
    return resolved


def create_submission(
    *,
    email: str,
    channel: Channel,
    language=None,
    body=None,
    slug: str | None = None,
    type_id: str | None = None,
    code: str | None = None,
    form_type: str | None = None,
) -> ContactForm:
    resolved_type = resolve_form_type(channel=channel, form_type=form_type, type_id=type_id, body=body)
    return ContactForm.objects.create(
        email=email,
        channel=channel,
        language=language,
        body=body,
        slug=slug,
        type=resolved_type,
        code=code,
    )


def update_status(*, pk: str, status: str) -> ContactForm:
    valid = {c[0] for c in ContactForm.Status.choices}
    if status not in valid:
        raise ValueError(f"Invalid status: {status}. Must be one of {valid}")
    submission = ContactForm.objects.select_related("channel", "language").get(pk=pk)
    submission.status = status
    submission.save(update_fields=["status", "modified_at"])
    return submission


def get_attachments(*, contact_form_pk: str) -> QuerySet[ContactFormAttachment]:
    return ContactFormAttachment.objects.filter(contact_form_id=contact_form_pk)
