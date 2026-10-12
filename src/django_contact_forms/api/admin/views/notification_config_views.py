# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Admin API views for form notification configuration (full CRUD)."""

from django.core.exceptions import ObjectDoesNotExist
from django.db import IntegrityError
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from pydantic import ValidationError
from rest_framework import status, viewsets
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework_simplejwt.authentication import JWTAuthentication

from django_contact_forms.api.admin.pagination import AdminPageNumberPagination
from django_contact_forms.api.admin.permissions import IsAdminUser
from django_contact_forms.schemas.requests.notification_config import (
    FormNotificationConfigCreateRequest,
    FormNotificationConfigUpdateRequest,
)
from django_contact_forms.schemas.responses.notification_config import (
    FormNotificationConfigListResponse,
    FormNotificationConfigResponse,
)
from django_contact_forms.services import notification_service

_ERROR_RESPONSES = {
    400: {"description": "Validation error"},
    401: {"description": "Authentication required"},
    403: {"description": "Permission denied"},
    404: {"description": "Not found"},
}


def _build_response(config) -> dict:
    return FormNotificationConfigResponse(
        id=config.pk,
        channel_id=config.channel_id,
        channel_idx=config.channel.idx,
        form_type=config.form_type,
        slug=config.slug,
        send_email=config.send_email,
        send_client_copy=config.send_client_copy,
        recipient_email=config.recipient_email,
    ).model_dump()


@extend_schema_view(
    list=extend_schema(tags=["Contact Form Notifications"]),
    create=extend_schema(tags=["Contact Form Notifications"]),
    retrieve=extend_schema(tags=["Contact Form Notifications"]),
    partial_update=extend_schema(tags=["Contact Form Notifications"]),
    destroy=extend_schema(tags=["Contact Form Notifications"]),
)
class NotificationConfigViewSet(viewsets.ViewSet):
    """Admin CRUD for form notification configuration."""

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAdminUser]
    access_area = "contact_forms.settings"

    @extend_schema(
        summary="List notification configs",
        description="Returns a paginated list of form notification configurations.",
        parameters=[
            OpenApiParameter(
                name="channel",
                location=OpenApiParameter.QUERY,
                type=str,
                description="Filter by channel idx",
            ),
            OpenApiParameter(
                name="page",
                location=OpenApiParameter.QUERY,
                type=int,
                description="Page number",
            ),
            OpenApiParameter(
                name="page_size",
                location=OpenApiParameter.QUERY,
                type=int,
                description="Items per page (max 100)",
            ),
        ],
        responses={200: FormNotificationConfigListResponse, **_ERROR_RESPONSES},
    )
    def list(self, request: Request, **kwargs) -> Response:
        qs = notification_service.list_configs(
            channel_idx=request.query_params.get("channel") or None,
        )
        paginator = AdminPageNumberPagination()
        page = paginator.paginate_queryset(qs, request)
        results = [_build_response(c) for c in page]
        response = FormNotificationConfigListResponse(
            count=paginator.page.paginator.count,
            next=paginator.get_next_link(),
            previous=paginator.get_previous_link(),
            results=results,
        )
        return Response(response.model_dump())

    @extend_schema(
        summary="Create notification config",
        description="Creates a new form notification configuration.",
        responses={201: FormNotificationConfigResponse, **_ERROR_RESPONSES},
    )
    def create(self, request: Request, **kwargs) -> Response:
        try:
            data = FormNotificationConfigCreateRequest(**request.data)
        except ValidationError as exc:
            return Response({"detail": exc.errors()}, status=status.HTTP_400_BAD_REQUEST)

        try:
            config = notification_service.create_config(
                channel_id=data.channel_id,
                form_type=data.form_type,
                slug=data.slug,
                send_email=data.send_email,
                send_client_copy=data.send_client_copy,
                recipient_email=data.recipient_email,
            )
        except ObjectDoesNotExist:
            return Response(
                {"detail": f"Channel {data.channel_id} not found."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except IntegrityError:
            return Response(
                {"detail": "Config for this channel/type/slug combination already exists."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(_build_response(config), status=status.HTTP_201_CREATED)

    @extend_schema(
        summary="Retrieve notification config",
        description="Returns a single notification config by primary key.",
        parameters=[
            OpenApiParameter(
                name="pk",
                location=OpenApiParameter.PATH,
                type=int,
                description="Config primary key",
            ),
        ],
        responses={200: FormNotificationConfigResponse, **_ERROR_RESPONSES},
    )
    def retrieve(self, request: Request, pk: int, **kwargs) -> Response:
        try:
            config = notification_service.get_config(pk=int(pk))
        except ObjectDoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(_build_response(config))

    @extend_schema(
        summary="Update notification config",
        description="Partially updates a notification config. Only provided fields are changed.",
        parameters=[
            OpenApiParameter(
                name="pk",
                location=OpenApiParameter.PATH,
                type=int,
                description="Config primary key",
            ),
        ],
        responses={200: FormNotificationConfigResponse, **_ERROR_RESPONSES},
    )
    def partial_update(self, request: Request, pk: int, **kwargs) -> Response:
        try:
            data = FormNotificationConfigUpdateRequest(**request.data)
        except ValidationError as exc:
            return Response({"detail": exc.errors()}, status=status.HTTP_400_BAD_REQUEST)

        try:
            config = notification_service.update_config(pk=int(pk), updates=data.model_dump(exclude_none=True))
        except ObjectDoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        except IntegrityError:
            return Response(
                {"detail": "Config for this channel/type/slug combination already exists."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(_build_response(config))

    @extend_schema(
        summary="Delete notification config",
        description="Permanently deletes a notification config.",
        parameters=[
            OpenApiParameter(
                name="pk",
                location=OpenApiParameter.PATH,
                type=int,
                description="Config primary key",
            ),
        ],
        responses={204: None, **_ERROR_RESPONSES},
    )
    def destroy(self, request: Request, pk: int, **kwargs) -> Response:
        try:
            notification_service.delete_config(pk=int(pk))
        except ObjectDoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(status=status.HTTP_204_NO_CONTENT)
