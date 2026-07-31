# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from django.urls import path

from django_contact_forms.api.admin.views.attachment_views import AttachmentDownloadView
from django_contact_forms.api.admin.views.booking_views import BookingViewSet
from django_contact_forms.api.admin.views.channel_integrations_views import (
    ChannelIntegrationsViewSet,
)
from django_contact_forms.api.admin.views.form_type_views import FormTypeAdminViewSet
from django_contact_forms.api.admin.views.lead_views import LeadViewSet
from django_contact_forms.api.admin.views.notification_config_views import NotificationConfigViewSet
from django_contact_forms.api.admin.views.offline_conversion_views import OfflineConversionViewSet
from django_contact_forms.api.admin.views.submission_views import SubmissionViewSet

urlpatterns = [
    # Channel integrations (read-only, used by the CMS to gate UI hints)
    path(
        "channels/<str:channel_idx>/integrations/",
        ChannelIntegrationsViewSet.as_view({"get": "retrieve"}),
        name="admin-channel-integrations",
    ),
    # Submissions (read-only)
    path(
        "submissions/",
        SubmissionViewSet.as_view({"get": "list"}),
        name="admin-submission-list",
    ),
    path(
        "submissions/<str:pk>/",
        SubmissionViewSet.as_view({"get": "retrieve", "patch": "partial_update"}),
        name="admin-submission-detail",
    ),
    # Attachment download
    path(
        "submissions/<str:pk>/attachments/<int:attachment_id>/download/",
        AttachmentDownloadView.as_view(),
        name="admin-attachment-download",
    ),
    # Form types (read-only; CMS type selector source)
    path(
        "form-types/",
        FormTypeAdminViewSet.as_view({"get": "list"}),
        name="admin-form-type-list",
    ),
    # Notification config (full CRUD)
    path(
        "notifications/",
        NotificationConfigViewSet.as_view({"get": "list", "post": "create"}),
        name="admin-notification-config-list",
    ),
    path(
        "notifications/<int:pk>/",
        NotificationConfigViewSet.as_view({"get": "retrieve", "patch": "partial_update", "delete": "destroy"}),
        name="admin-notification-config-detail",
    ),
    # Leads
    path("leads/", LeadViewSet.as_view({"get": "list"}), name="admin-lead-list"),
    path("leads/summary/", LeadViewSet.as_view({"get": "summary"}), name="admin-lead-summary"),
    path(
        "leads/<int:pk>/",
        LeadViewSet.as_view({"get": "retrieve", "patch": "partial_update"}),
        name="admin-lead-detail",
    ),
    path(
        "leads/<int:pk>/transition/",
        LeadViewSet.as_view({"post": "transition"}),
        name="admin-lead-transition",
    ),
    # Bookings (read-only)
    path("bookings/", BookingViewSet.as_view({"get": "list"}), name="admin-booking-list"),
    path(
        "bookings/<int:pk>/",
        BookingViewSet.as_view({"get": "retrieve"}),
        name="admin-booking-detail",
    ),
    # Offline conversions
    path(
        "offline-conversions/",
        OfflineConversionViewSet.as_view({"get": "list"}),
        name="admin-offline-conversion-list",
    ),
    path(
        "offline-conversions/<int:pk>/",
        OfflineConversionViewSet.as_view({"get": "retrieve"}),
        name="admin-offline-conversion-detail",
    ),
    path(
        "offline-conversions/<int:pk>/retry/",
        OfflineConversionViewSet.as_view({"post": "retry"}),
        name="admin-offline-conversion-retry",
    ),
]
