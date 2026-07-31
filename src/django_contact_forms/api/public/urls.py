# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from django.urls import path

from django_contact_forms.api.public.booking_views import BookingViewSet
from django_contact_forms.api.public.form_type_views import FormTypeViewSet
from django_contact_forms.api.public.views import SubmitViewSet

urlpatterns = [
    path(
        "<str:channel_idx>/form-types/",
        FormTypeViewSet.as_view({"get": "list"}),
        name="public-form-types",
    ),
    path("<str:channel_idx>/submit/", SubmitViewSet.as_view({"post": "create"}), name="public-submit"),
    path(
        "<str:channel_idx>/submit/<str:type_id>/",
        SubmitViewSet.as_view({"post": "create"}),
        name="public-submit-with-type",
    ),
    path(
        "<str:channel_idx>/bookings/slots/",
        BookingViewSet.as_view({"get": "list"}),
        name="public-booking-slots",
    ),
    path(
        "<str:channel_idx>/bookings/",
        BookingViewSet.as_view({"post": "create"}),
        name="public-booking-create",
    ),
]
