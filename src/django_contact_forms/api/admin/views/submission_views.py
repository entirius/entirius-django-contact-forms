# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Admin API views for contact form submissions (read-only)."""

from django.core.exceptions import ObjectDoesNotExist
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import status, viewsets
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework_simplejwt.authentication import JWTAuthentication

from django_contact_forms.api.admin.pagination import AdminPageNumberPagination
from django_contact_forms.api.admin.permissions import IsAdminUser
from django_contact_forms.schemas.requests.status import StatusUpdateRequest
from django_contact_forms.schemas.responses.attachment import AttachmentResponse
from django_contact_forms.schemas.responses.submission import ContactFormListResponse, ContactFormResponse
from django_contact_forms.services import contact_form_service

_ERROR_RESPONSES = {
    401: {"description": "Authentication required"},
    403: {"description": "Permission denied"},
    404: {"description": "Not found"},
}


def _build_response(submission) -> dict:
    attachments = submission.contactformattachment_set.all()
    attachment_list = [
        AttachmentResponse(
            id=a.pk,
            name=a.name,
            created_at=a.created_at,
        ).model_dump()
        for a in attachments
    ]
    response = ContactFormResponse(
        id=submission.id,
        email=submission.email,
        channel_idx=submission.channel.idx,
        slug=submission.slug,
        type=submission.type,
        code=submission.code,
        language=submission.language.iso2 if submission.language else None,
        body=submission.body,
        status=submission.status,
        attachments=attachment_list,
        created_at=submission.created_at,
    )
    return response.model_dump()


@extend_schema_view(
    list=extend_schema(tags=["Contact Form Submissions"]),
    retrieve=extend_schema(tags=["Contact Form Submissions"]),
    partial_update=extend_schema(tags=["Contact Form Submissions"]),
)
class SubmissionViewSet(viewsets.ViewSet):
    """Admin read-only access to contact form submissions."""

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAdminUser]

    @extend_schema(
        summary="List contact form submissions",
        description="Returns a paginated list of contact form submissions with optional filters.",
        parameters=[
            OpenApiParameter(
                name="type",
                location=OpenApiParameter.QUERY,
                type=str,
                description="Filter by form type",
            ),
            OpenApiParameter(
                name="slug",
                location=OpenApiParameter.QUERY,
                type=str,
                description="Filter by form slug",
            ),
            OpenApiParameter(
                name="channel",
                location=OpenApiParameter.QUERY,
                type=str,
                description="Filter by channel idx",
            ),
            OpenApiParameter(
                name="search",
                location=OpenApiParameter.QUERY,
                type=str,
                description="Search by id, email, or code",
            ),
            OpenApiParameter(
                name="status",
                location=OpenApiParameter.QUERY,
                type=str,
                description="Filter by status: todo, in_progress, done",
            ),
            OpenApiParameter(
                name="ordering",
                location=OpenApiParameter.QUERY,
                type=str,
                description="Order by field: created_at, email, type, status (prefix with - for descending)",
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
        responses={200: ContactFormListResponse, **_ERROR_RESPONSES},
    )
    def list(self, request: Request, **kwargs) -> Response:
        try:
            qs = contact_form_service.list_submissions(
                channel_idx=request.query_params.get("channel") or None,
                form_type=request.query_params.get("type") or None,
                slug=request.query_params.get("slug") or None,
                search=request.query_params.get("search") or None,
                ordering=request.query_params.get("ordering") or None,
                status=request.query_params.get("status") or None,
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        paginator = AdminPageNumberPagination()
        page = paginator.paginate_queryset(qs, request)
        results = [_build_response(s) for s in page]
        response = ContactFormListResponse(
            count=paginator.page.paginator.count,
            next=paginator.get_next_link(),
            previous=paginator.get_previous_link(),
            results=results,
        )
        return Response(response.model_dump())

    @extend_schema(
        summary="Retrieve contact form submission",
        description="Returns a single submission with its body and attachments.",
        parameters=[
            OpenApiParameter(
                name="pk",
                location=OpenApiParameter.PATH,
                type=str,
                description="12-digit submission identifier",
            ),
        ],
        responses={200: ContactFormResponse, **_ERROR_RESPONSES},
    )
    def retrieve(self, request: Request, pk: str, **kwargs) -> Response:
        try:
            submission = contact_form_service.get_submission(pk=pk)
        except ObjectDoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(_build_response(submission))

    @extend_schema(
        summary="Update submission status",
        description="Updates the processing status of a contact form submission.",
        parameters=[
            OpenApiParameter(
                name="pk",
                location=OpenApiParameter.PATH,
                type=str,
                description="12-digit submission identifier",
            ),
        ],
        request=StatusUpdateRequest,
        responses={200: ContactFormResponse, **_ERROR_RESPONSES},
    )
    def partial_update(self, request: Request, pk: str, **kwargs) -> Response:
        try:
            payload = StatusUpdateRequest(**request.data)
        except Exception:
            return Response(
                {"detail": "Invalid status. Must be one of: todo, in_progress, done."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            submission = contact_form_service.update_status(pk=pk, status=payload.status)
        except ObjectDoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(_build_response(submission))
