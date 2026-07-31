# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Admin API view for per-channel integration state (google_ads + bookings)."""

from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import status, viewsets
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework_simplejwt.authentication import JWTAuthentication

from django_contact_forms.api.admin.permissions import IsAdminUser
from django_contact_forms.models import Channel
from django_contact_forms.schemas.responses.channel_integrations import (
    ChannelIntegrationsResponse,
)
from django_contact_forms.services import channel_integrations_service

_ERROR_RESPONSES = {
    401: {"description": "Authentication required"},
    403: {"description": "Permission denied"},
    404: {"description": "Channel not found"},
}


@extend_schema_view(retrieve=extend_schema(tags=["Integrations"]))
class ChannelIntegrationsViewSet(viewsets.ViewSet):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAdminUser]

    @extend_schema(
        summary="Retrieve channel integrations state",
        description=(
            "Returns ``google_ads_enabled`` and ``bookings_enabled`` for the given "
            "channel. Each flag is the logical AND of the global ContactFormsSettings "
            "toggle and the per-channel config's own enabled flag."
        ),
        parameters=[
            OpenApiParameter(name="channel_idx", location=OpenApiParameter.PATH, type=str),
        ],
        responses={200: ChannelIntegrationsResponse, **_ERROR_RESPONSES},
    )
    def retrieve(self, request: Request, channel_idx: str, **kwargs) -> Response:
        try:
            data = channel_integrations_service.get_integrations(channel_idx=channel_idx)
        except Channel.DoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(ChannelIntegrationsResponse(**data).model_dump())
