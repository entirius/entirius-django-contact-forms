# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Public API view for contact form submissions."""

import json

from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from pydantic import ValidationError
from rest_framework import status, viewsets
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response

from django_contact_forms.api.public.authentication import APIKeyAuthentication
from django_contact_forms.api.public.throttling import ContactFormSubmitThrottle
from django_contact_forms.models import ContactFormAttachment
from django_contact_forms.schemas.requests.submission import ContactFormSubmitRequest
from django_contact_forms.schemas.responses.submission import ContactFormResponse
from django_contact_forms.services import (
    contact_form_service,
    lead_creation_rule_service,
    lead_service,
    notification_service,
)
from django_contact_forms.utils.exceptions import (
    AttachmentCountLimitReached,
    AttachmentSizeLimitReached,
    JSONTooLargeException,
)
from django_contact_forms.utils.workers import get_language

_ERROR_RESPONSES = {
    400: {"description": "Validation error"},
    401: {"description": "Authentication required (X-API-KEY)"},
}


_TRUTHY = frozenset({True, "true", "True", "1"})


def _wants_copy(body) -> bool:
    """Whether the submitter asked for a copy via ``body.send_copy``."""
    return isinstance(body, dict) and body.get("send_copy") in _TRUTHY


def _collect_attachments(request: Request, contact_form) -> list[int]:
    """Process uploaded files and return list of attachment PKs."""
    attachments_pk_list = []
    for key in request.FILES:
        attachment_file = request.FILES[key]
        attachment = ContactFormAttachment.objects.create(
            name=attachment_file.name,
            contact_form=contact_form,
            attachment=attachment_file,
        )
        attachments_pk_list.append(attachment.pk)
    return attachments_pk_list


class _FakeRequest:
    """Minimal object to satisfy get_language(request, ...) signature."""

    def __init__(self):
        self.messages = []


@extend_schema_view(
    create=extend_schema(tags=["Contact Form Submission"]),
)
class SubmitViewSet(viewsets.ViewSet):
    """Public endpoint for submitting contact forms."""

    authentication_classes = [APIKeyAuthentication]
    permission_classes = [AllowAny]
    throttle_classes = [ContactFormSubmitThrottle]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    @extend_schema(
        summary="Submit contact form",
        description=(
            "Creates a new contact form submission. Supports multipart/form-data "
            "for file uploads. Authenticated via X-API-KEY header."
        ),
        parameters=[
            OpenApiParameter(
                name="channel_idx",
                location=OpenApiParameter.PATH,
                type=str,
                description="Channel identifier",
            ),
            OpenApiParameter(
                name="type_id",
                location=OpenApiParameter.PATH,
                type=str,
                required=False,
                description="Optional form type identifier from URL",
            ),
        ],
        responses={201: ContactFormResponse, **_ERROR_RESPONSES},
    )
    def create(self, request: Request, channel_idx: str, type_id: str | None = None, **kwargs) -> Response:
        channel = request.auth  # set by APIKeyAuthentication

        # Parse form data — multipart QueryDict wraps values in lists
        raw = request.data
        data = {}
        for key in raw:
            if key not in request.FILES:
                val = raw.getlist(key) if hasattr(raw, "getlist") else raw[key]
                data[key] = val[0] if isinstance(val, list) and len(val) == 1 else val

        # Body may come as a JSON string in multipart
        if "body" in data and isinstance(data["body"], str):
            try:
                data["body"] = json.loads(data["body"])
            except (json.JSONDecodeError, TypeError):
                pass

        try:
            payload = ContactFormSubmitRequest(**data)
        except ValidationError as exc:
            return Response({"detail": exc.errors()}, status=status.HTTP_400_BAD_REQUEST)

        # Resolve language
        fake_request = _FakeRequest()
        language, _ = get_language(fake_request, channel, payload.language)

        # Create submission
        try:
            contact_form = contact_form_service.create_submission(
                email=payload.email,
                channel=channel,
                language=language,
                body=payload.body,
                slug=payload.slug,
                type_id=type_id,
                form_type=payload.form_type,
                code=payload.code,
            )
        except JSONTooLargeException:
            return Response(
                {"detail": "JSON body is too large."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Collect attachments
        try:
            attachments_pk_list = _collect_attachments(request, contact_form)
        except AttachmentCountLimitReached:
            return Response(
                {"detail": "Attachment count limit exceeded."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except AttachmentSizeLimitReached:
            return Response(
                {"detail": "Attachment size limit exceeded."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Dispatch email notification. Routing keys off the resolved type stored
        # on the submission (not the raw URL type_id), so storefront traffic that
        # carries the type in the body is now routable.
        decision = notification_service.resolve_email_dispatch(channel, form_type=contact_form.type, slug=payload.slug)
        send_client_copy = decision.send_client_copy and _wants_copy(contact_form.body) and bool(contact_form.email)
        if decision.send_admin or send_client_copy:
            recipient = decision.recipient or channel.admin_email
            notification_service.dispatch_email(
                contact_form.pk,
                recipient,
                attachments_pk_list,
                send_admin=decision.send_admin,
                send_client_copy=send_client_copy,
            )

        # Opt-in Lead creation — driven by LeadCreationRule (Grappelli-managed).
        # Off by default for every channel/form; an operator explicitly turns it
        # on per (channel, form_type, slug) via the Django admin.
        should_create, source_type = lead_creation_rule_service.should_create_lead(
            channel, form_type=contact_form.type, slug=payload.slug
        )
        if should_create:
            attribution = lead_creation_rule_service.extract_attribution(contact_form.body)
            lead_service.create_lead(
                contact_form=contact_form,
                source_type=source_type,
                email=contact_form.email,
                **attribution,
            )

        response = ContactFormResponse(
            id=contact_form.id,
            email=contact_form.email,
            channel_idx=channel.idx,
            slug=contact_form.slug,
            type=contact_form.type,
            code=contact_form.code,
            language=language.iso2 if language else None,
            body=contact_form.body,
            status=contact_form.status,
            attachments=[],
            created_at=contact_form.created_at,
        )
        return Response(response.model_dump(), status=status.HTTP_201_CREATED)
