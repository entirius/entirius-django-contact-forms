# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Admin API views for Lead CRUD + status transition + summary."""

from django.core.exceptions import ObjectDoesNotExist
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from pydantic import ValidationError
from rest_framework import status, viewsets
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework_simplejwt.authentication import JWTAuthentication

from django_contact_forms.api.admin.pagination import AdminPageNumberPagination
from django_contact_forms.api.admin.permissions import IsAdminUser
from django_contact_forms.models import Lead
from django_contact_forms.schemas.requests.lead import LeadTransitionRequest, LeadUpdateRequest
from django_contact_forms.schemas.responses.lead import (
    LeadListResponse,
    LeadResponse,
    LeadStatusCount,
    LeadSummaryResponse,
)
from django_contact_forms.services import lead_service
from django_contact_forms.services.exceptions import InvalidLeadTransitionError
from django_contact_forms.utils.v2_errors import raise_pydantic_as_drf

_ERROR_RESPONSES = {
    400: {"description": "Validation or transition error"},
    401: {"description": "Authentication required"},
    403: {"description": "Permission denied"},
    404: {"description": "Not found"},
}


def _serialize(lead: Lead) -> dict:
    return LeadResponse(
        id=lead.pk,
        contact_form_id=lead.contact_form.pk,
        channel_idx=lead.contact_form.channel.idx,
        name=lead.name,
        email=lead.email,
        phone=lead.phone,
        company=lead.company,
        source_type=lead.source_type,
        contact_date=lead.contact_date,
        message=lead.message,
        gclid=lead.gclid,
        hashed_email=lead.hashed_email,
        attribution_method=lead.attribution_method,
        campaign_name=lead.campaign_name,
        source=lead.source,
        medium=lead.medium,
        landing_page=lead.landing_page,
        status=lead.status,
        deal_value=lead.deal_value,
        status_changed_at=lead.status_changed_at,
        notes=lead.notes,
        ads_conversion_imported=lead.ads_conversion_imported,
        ads_imported_at=lead.ads_imported_at,
    ).model_dump()


@extend_schema_view(
    list=extend_schema(tags=["Leads"]),
    retrieve=extend_schema(tags=["Leads"]),
    partial_update=extend_schema(tags=["Leads"]),
    transition=extend_schema(tags=["Leads"]),
    summary=extend_schema(tags=["Leads"]),
)
class LeadViewSet(viewsets.ViewSet):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAdminUser]
    access_area = "contact_forms.leads"

    @extend_schema(
        summary="List leads",
        description="Paginated list, filterable by channel/status/source_type and searchable on name/email/gclid.",
        parameters=[
            OpenApiParameter(name="channel", type=str),
            OpenApiParameter(name="status", type=str),
            OpenApiParameter(name="source_type", type=str),
            OpenApiParameter(name="search", type=str),
            OpenApiParameter(name="page", type=int),
            OpenApiParameter(name="page_size", type=int),
        ],
        responses={200: LeadListResponse, **_ERROR_RESPONSES},
    )
    def list(self, request: Request, **kwargs) -> Response:
        try:
            qs = lead_service.list_leads(
                channel_idx=request.query_params.get("channel") or None,
                status=request.query_params.get("status") or None,
                source_type=request.query_params.get("source_type") or None,
                search=request.query_params.get("search") or None,
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        paginator = AdminPageNumberPagination()
        page = paginator.paginate_queryset(qs, request)
        results = [_serialize(lead) for lead in page]
        return Response(
            LeadListResponse(
                count=paginator.page.paginator.count,
                next=paginator.get_next_link(),
                previous=paginator.get_previous_link(),
                results=results,
            ).model_dump()
        )

    @extend_schema(
        summary="Retrieve lead",
        parameters=[OpenApiParameter(name="pk", location=OpenApiParameter.PATH, type=int)],
        responses={200: LeadResponse, **_ERROR_RESPONSES},
    )
    def retrieve(self, request: Request, pk: int, **kwargs) -> Response:
        try:
            lead = lead_service.get_lead(pk=int(pk))
        except (Lead.DoesNotExist, ObjectDoesNotExist):
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(_serialize(lead))

    @extend_schema(
        summary="Patch lead",
        description="PATCH editable fields (name, phone, company, deal_value, notes). Use /transition/ for status.",
        request=LeadUpdateRequest,
        responses={200: LeadResponse, **_ERROR_RESPONSES},
    )
    def partial_update(self, request: Request, pk: int, **kwargs) -> Response:
        try:
            payload = LeadUpdateRequest(**request.data)
        except ValidationError as exc:
            raise_pydantic_as_drf(exc)
        try:
            lead = lead_service.get_lead(pk=int(pk))
        except (Lead.DoesNotExist, ObjectDoesNotExist):
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        updates = {k: v for k, v in payload.model_dump(exclude_unset=True).items() if v is not None}
        lead = lead_service.update_lead(lead=lead, updates=updates)
        return Response(_serialize(lead))

    @extend_schema(
        summary="Transition lead status",
        description="Move a lead through the FSM. Allowed transitions enforced by the service.",
        request=LeadTransitionRequest,
        responses={200: LeadResponse, **_ERROR_RESPONSES},
    )
    def transition(self, request: Request, pk: int, **kwargs) -> Response:
        try:
            payload = LeadTransitionRequest(**request.data)
        except ValidationError as exc:
            raise_pydantic_as_drf(exc)
        try:
            lead = lead_service.get_lead(pk=int(pk))
        except (Lead.DoesNotExist, ObjectDoesNotExist):
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        old_status = lead.status
        try:
            lead = lead_service.transition_status(
                lead=lead, new_status=payload.new_status, deal_value=payload.deal_value
            )
        except InvalidLeadTransitionError:
            return Response(
                {
                    "error": "INVALID_TRANSITION",
                    "from_status": old_status,
                    "to_status": payload.new_status,
                    "message": f"Cannot transition Lead {pk} from {old_status} to {payload.new_status}",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(_serialize(lead))

    @extend_schema(
        summary="Lead summary by status",
        parameters=[OpenApiParameter(name="channel", type=str)],
        responses={200: LeadSummaryResponse, **_ERROR_RESPONSES},
    )
    def summary(self, request: Request, **kwargs) -> Response:
        rows = lead_service.summary_by_status(channel_idx=request.query_params.get("channel") or None)
        by_status = [LeadStatusCount(status=row["status"], count=row["count"]) for row in rows]
        return Response(LeadSummaryResponse(by_status=by_status).model_dump())
