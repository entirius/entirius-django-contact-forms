# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""The one key check of the widget routes (X-API-KEY: contact form, form types, booking).

With ``django_access`` installed a key is an access token checked by ``verify_api_key`` (scope + channel pin); the
legacy table is never read on that path — legacy keys live on as imported tokens (D28). Without the module: today's
legacy query, unchanged.
"""

from types import SimpleNamespace

from django.apps import apps

from django_contact_forms.models import APIKey, Channel

SUBMIT_SCOPE = "contact_forms.submit"
BOOKING_SCOPE = "contact_forms.booking"
LEGACY_SCOPES = {SUBMIT_SCOPE: APIKey.Scope.CONTACT_FORM, BOOKING_SCOPE: APIKey.Scope.BOOKING}
_HEADER = "HTTP_X_API_KEY"


def access_installed() -> bool:
    return apps.is_installed("django_access")


def mask_key(key: str) -> str:
    """What an admin page shows of a key: its last four characters."""
    return f"…{key[-4:]}"


def key_is_valid(request, *, scopes: tuple[str, ...], channel: Channel) -> bool:
    """True when X-API-KEY carries a key for any of ``scopes`` on ``channel``."""
    key = request.META.get(_HEADER)
    if not key:
        return False
    if access_installed():
        return any(_token_is_valid(request, key, scope, channel.idx) for scope in scopes)
    legacy_scopes = [LEGACY_SCOPES[scope] for scope in scopes]
    return APIKey.objects.filter(key=key, channel=channel, scope__in=legacy_scopes).exists()


def _token_is_valid(request, key: str, scope: str, channel_idx: str) -> bool:
    """``verify_api_key`` sees only X-API-KEY: the X-API-ADMIN-KEY alias never stands in on a widget route."""
    from django_access.services.tokens import verify_api_key

    token = verify_api_key(SimpleNamespace(META={_HEADER: key}), scope, channel_idx)
    if token is not None:
        request.access_token = token
    return token is not None


def token_command(scope: str) -> str:
    """What replaces the legacy key command when access is installed."""
    return f"manage.py access_token create --scope {scope} --channel <idx> --application <name>"
