# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Admin API view listing form types for a channel (CMS type selector source)."""

from django.core.exceptions import ObjectDoesNotExist
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status, viewsets
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework_simplejwt.authentication import JWTAuthentication

from django_contact_forms.api.admin.permissions import IsAdminUser
from django_contact_forms.schemas.responses.form_type import FormTypeListResponse, FormTypeResponse
from django_contact_forms.services import contact_form_service


class FormTypeAdminViewSet(viewsets.ViewSet):
    """Admin read-only list of a channel's form types."""

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAdminUser]
    access_area = "contact_forms.settings"

    @extend_schema(
        summary="List form types (admin)",
        description="Returns the configured form types for the channel given by ``channel_idx``.",
        parameters=[
            OpenApiParameter(
                name="channel_idx",
                location=OpenApiParameter.QUERY,
                type=str,
                required=True,
                description="Channel identifier",
            ),
        ],
        responses={
            200: FormTypeListResponse,
            400: {"description": "Missing or unknown channel_idx"},
            401: {"description": "Authentication required"},
            403: {"description": "Permission denied"},
        },
        tags=["Contact Form Types"],
    )
    def list(self, request: Request, **kwargs) -> Response:
        channel_idx = request.query_params.get("channel_idx")
        if not channel_idx:
            return Response(
                {"detail": "channel_idx query parameter is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            channel = contact_form_service.get_channel(idx=channel_idx)
        except ObjectDoesNotExist:
            return Response(
                {"detail": f"Channel '{channel_idx}' not found."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        form_types = contact_form_service.list_form_types(channel=channel)
        response = FormTypeListResponse(results=[FormTypeResponse.model_validate(ft) for ft in form_types])
        return Response(response.model_dump(), status=status.HTTP_200_OK)
