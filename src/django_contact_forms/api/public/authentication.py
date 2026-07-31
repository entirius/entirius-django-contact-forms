# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""X-API-KEY authentication for DRF (wraps existing v1 pattern).

Optional ``required_scope`` makes the auth class scope-aware. The default
APIKeyAuthentication accepts any scope (back-compat for the contact-form
submit endpoint, which keeps working with all keys including legacy rows
that default to scope="contact_form"). Scoped subclasses (e.g.
BookingAPIKeyAuthentication) reject keys that don't match.
"""

from django.contrib.auth.models import AnonymousUser
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed

from django_contact_forms.models import APIKey, Channel


class APIKeyAuthentication(BaseAuthentication):
    """Default: accepts contact-form-scoped keys (and legacy rows with no scope set)."""

    required_scope: str = APIKey.Scope.CONTACT_FORM

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

        if not APIKey.objects.filter(key=api_key, channel=channel, scope=self.required_scope).exists():
            raise AuthenticationFailed(f"Invalid API key for scope '{self.required_scope}'.")

        return (AnonymousUser(), channel)


class BookingAPIKeyAuthentication(APIKeyAuthentication):
    required_scope = APIKey.Scope.BOOKING
