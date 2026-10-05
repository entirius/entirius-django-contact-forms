# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from celery import current_app
from django.views.decorators.csrf import csrf_exempt
from django_utils.api.decorators import parse_form, require_http_method
from django_utils.api.exceptions import BadRequest
from django_utils.api.responses import Response
from process_logger import ProcessLogger

from django_contact_forms import settings
from django_contact_forms.api.public.throttling import ContactFormSubmitV1Throttle
from django_contact_forms.models import ContactForm, ContactFormAttachment
from django_contact_forms.tasks.send_contact_form_email import send_contact_form_email
from django_contact_forms.utils.decorators import channel_view, throttled
from django_contact_forms.utils.exceptions import (
    AttachmentCountLimitReached,
    AttachmentSizeLimitReached,
    JSONTooLargeException,
)
from django_contact_forms.utils.payloads import ContactFormPayload
from django_contact_forms.utils.workers import get_language


def collect_attachment(request, logger, contact_form):
    if "multipart/form-data" not in request.content_type:
        logger.set_code(4006)
        logger.error("Content type is not multipart/form-data")
        return []
    try:
        all_attachments = request.FILES.keys()
    except Exception as e:
        logger.exception(e)
        logger.set_code(4006)
        return []

    attachments_pk_list = []
    for attachment in all_attachments:
        attachment_file = request.FILES.get(attachment)
        try:
            form_attachment_obj = ContactFormAttachment.objects.create(
                name=attachment_file.name, contact_form=contact_form, attachment=attachment_file
            )
            attachments_pk_list.append(form_attachment_obj.pk)
        except AttachmentCountLimitReached as e:
            logger.exception(e)
            logger.set_code(4008)
            raise BadRequest("4008") from e
        except AttachmentSizeLimitReached as e:
            logger.exception(e)
            logger.set_code(4009)
            raise BadRequest("4009") from e
        except Exception as e:
            logger.exception(e)
            logger.set_code(4003)
            raise BadRequest("4003") from e

    return attachments_pk_list


def create_contact(request, logger, body: ContactFormPayload, type_id: str = None):
    language, _ = get_language(request, request.channel, body.language)
    contact_form = None
    try:
        contact_form = ContactForm.objects.create(
            email=body.email,
            slug=body.slug,
            channel=request.channel,
            language=language,
            body=body.body,
            type=type_id,
            code=body.code,
        )

    except JSONTooLargeException as e:
        logger.exception(e)
        logger.set_code(4005)
        raise BadRequest("4005") from e

    except Exception as e:
        logger.exception(e)
        logger.set_code(4004)
        raise BadRequest("4004") from e

    attachments_pk_list = collect_attachment(request, logger, contact_form)

    if contact_form and settings.CONTACT_FORM_SEND_ADMIN_EMAIL:
        existing_queues = current_app.amqp.queues
        queue_names = list(existing_queues)
        if "contact_forms" in queue_names:
            try:
                send_contact_form_email.apply_async(
                    args=[contact_form.pk, request.channel.admin_email, attachments_pk_list], queue="contact_forms"
                )
            except Exception as e:
                logger.exception(e)
                send_contact_form_email(contact_form.pk, request.channel.admin_email, attachments_pk_list)
        else:
            send_contact_form_email(contact_form.pk, request.channel.admin_email, attachments_pk_list)
            logger.warning("The 'contact_forms' queue does not exist. Skipping task, doing it synchronously.")
    else:
        logger.warning("Skipping task as contact form or admin email sending is not configured.")

    return Response(contact_form.as_data(), messages=request.messages)


@csrf_exempt
@channel_view
@require_http_method("POST")
@throttled(ContactFormSubmitV1Throttle)
@parse_form(ContactFormPayload.Schema)
def create_contact_form(request, body: ContactFormPayload, *args, **kwargs):
    logger = ProcessLogger("DJANGO_FORMS - create_contact_form")
    return create_contact(request, logger, body)


@csrf_exempt
@channel_view
@require_http_method("POST")
@throttled(ContactFormSubmitV1Throttle)
@parse_form(ContactFormPayload.Schema)
def create_contact_form_with_type(request, body: ContactFormPayload, type_id: str, *args, **kwargs):
    logger = ProcessLogger("DJANGO_FORMS - create_contact_form_with_type")
    return create_contact(request, logger, body, type_id)
