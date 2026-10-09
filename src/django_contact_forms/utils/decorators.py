# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from functools import wraps

from django_utils.api.decorators import api_view
from django_utils.api.exceptions import NotFound, Unauthorized

from django_contact_forms.models import Channel
from django_contact_forms.utils.api_keys import BOOKING_SCOPE, SUBMIT_SCOPE, key_is_valid

# v1 contract: a booking key submits contact forms too.
V1_SCOPES = (SUBMIT_SCOPE, BOOKING_SCOPE)


def channel_view(view):
    def is_allowed(request):
        return key_is_valid(request, scopes=V1_SCOPES, channel=request.channel, legacy_any_scope=True)

    @wraps(view)
    @api_view
    def _wrapped(request, channel_idx=None, *args, **kwargs):
        channel = Channel.objects.filter(idx=channel_idx).first()
        request.channel = channel
        request.messages = []

        if channel is not None:
            passed = is_allowed(request)
            if passed:
                response = view(request, channel_idx=channel_idx, *args, **kwargs)  # noqa: B026
                return response
            else:
                raise Unauthorized("Invalid api key")
        else:
            raise NotFound("Channel does not exist")

    return _wrapped
