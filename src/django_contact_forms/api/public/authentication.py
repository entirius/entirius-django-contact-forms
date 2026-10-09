# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""X-API-KEY authentication for DRF (wraps existing v1 pattern).

Each class accepts one scope: ``APIKeyAuthentication`` contact-form keys (``contact_forms.submit``),
``BookingAPIKeyAuthentication`` booking keys (``contact_forms.booking``). The key check is
``utils.api_keys.key_is_valid`` — an access token when django_access is installed, else the legacy table.
"""

from django.contrib.auth.models import AnonymousUser
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed

from django_contact_forms.models import Channel
from django_contact_forms.utils.api_keys import BOOKING_SCOPE, LEGACY_SCOPES, SUBMIT_SCOPE, key_is_valid


class APIKeyAuthentication(BaseAuthentication):
    """Default: accepts contact-form-scoped keys. ``request.auth`` is the ``Channel`` the views read."""

    scope: str = SUBMIT_SCOPE

    def authenticate_header(self, request):
        return "X-API-KEY"

    def authenticate(self, request):
        api_key = request.headers.get("X-API-KEY")
        if not api_key:
            raise AuthenticationFailed("X-API-KEY header is required.")

        channel_idx = request.parser_context.get("kwargs", {}).get("channel_idx")
        if not channel_idx:
            raise AuthenticationFailed("Channel identifier is required.")

        try:
            channel = Channel.objects.get(idx=channel_idx)
        except Channel.DoesNotExist as exc:
            raise AuthenticationFailed(f"Channel '{channel_idx}' not found.") from exc

        if not key_is_valid(request, scopes=(self.scope,), channel=channel):
            raise AuthenticationFailed(f"Invalid API key for scope '{LEGACY_SCOPES[self.scope]}'.")

        return (AnonymousUser(), channel)


class BookingAPIKeyAuthentication(APIKeyAuthentication):
    scope = BOOKING_SCOPE
