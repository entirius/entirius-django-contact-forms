# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Admin API view for downloading contact form attachments."""

import os

from django.core.exceptions import ObjectDoesNotExist
from django.http import FileResponse
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.authentication import JWTAuthentication

from django_contact_forms.api.admin.permissions import IsAdminUser
from django_contact_forms.models import ContactFormAttachment

_ERROR_RESPONSES = {
    401: {"description": "Authentication required"},
    403: {"description": "Permission denied"},
    404: {"description": "Not found"},
}


class AttachmentDownloadView(APIView):
    """Download a contact form attachment file."""

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAdminUser]
    access_area = "contact_forms.submissions"
    access_levels = {"GET": "write"}

    @extend_schema(
        tags=["Contact Form Submissions"],
        summary="Download attachment",
        description="Streams the attachment file with Content-Disposition header.",
        parameters=[
            OpenApiParameter(
                name="pk",
                location=OpenApiParameter.PATH,
                type=str,
                description="Contact form identifier",
            ),
            OpenApiParameter(
                name="attachment_id",
                location=OpenApiParameter.PATH,
                type=int,
                description="Attachment primary key",
            ),
        ],
        responses={200: bytes, **_ERROR_RESPONSES},
    )
    def get(self, request: Request, pk: str, attachment_id: int) -> Response:
        try:
            attachment = ContactFormAttachment.objects.get(pk=attachment_id, contact_form_id=pk)
        except ObjectDoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        file_path = attachment.attachment.path
        if not os.path.exists(file_path):
            return Response(
                {"detail": "File not found on disk."},
                status=status.HTTP_404_NOT_FOUND,
            )

        filename = attachment.name or os.path.basename(file_path)
        return FileResponse(
            open(file_path, "rb"),
            as_attachment=True,
            filename=filename,
        )
