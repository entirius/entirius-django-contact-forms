# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from django.urls import include, path

from django_contact_forms import settings
from django_contact_forms.views.views import create_contact_form, create_contact_form_with_type

# v1 (existing, untouched)
api_paths = [
    path("contact_form/", create_contact_form, name="create_contact_form"),
    path("contact_form/<str:type_id>/", create_contact_form_with_type, name="create_contact_form_with_type"),
]

urlpatterns = [
    # v1
    path(f"{settings.BASE_URL}/contact/<str:version>/<str:channel_idx>/", include(api_paths)),
    # v2 admin
    path("api/contact-forms/v2/admin/", include("django_contact_forms.api.admin.urls")),
    # v2 public
    path("api/contact-forms/v2/", include("django_contact_forms.api.public.urls")),
]
