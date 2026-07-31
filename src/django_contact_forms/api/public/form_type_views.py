# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Public API view exposing a channel's configured form types.

Lets storefronts render the type selector from the backend instead of
hardcoding the list. Authenticated via X-API-KEY (channel resolved from the key).
"""

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status, viewsets
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response

from django_contact_forms.api.public.authentication import APIKeyAuthentication
from django_contact_forms.api.public.throttling import FormTypeListThrottle
from django_contact_forms.schemas.responses.form_type import FormTypeListResponse, FormTypeResponse
from django_contact_forms.services import contact_form_service


class FormTypeViewSet(viewsets.ViewSet):
    """Public read-only list of the authenticated channel's form types."""

    authentication_classes = [APIKeyAuthentication]
    permission_classes = [AllowAny]
    throttle_classes = [FormTypeListThrottle]

    @extend_schema(
        summary="List form types",
        description="Returns the configured form types for the channel resolved from the API key.",
        parameters=[
            OpenApiParameter(
                name="channel_idx",
                location=OpenApiParameter.PATH,
                type=str,
                description="Channel identifier",
            ),
        ],
        responses={200: FormTypeListResponse, 401: {"description": "Authentication required (X-API-KEY)"}},
        tags=["Contact Form Types"],
    )
    def list(self, request: Request, channel_idx: str, **kwargs) -> Response:
        channel = request.auth  # set by APIKeyAuthentication
        form_types = contact_form_service.list_form_types(channel=channel)
        response = FormTypeListResponse(results=[FormTypeResponse.model_validate(ft) for ft in form_types])
        return Response(response.model_dump(), status=status.HTTP_200_OK)
