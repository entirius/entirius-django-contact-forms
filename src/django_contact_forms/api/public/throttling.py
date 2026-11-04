# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Throttles for the public (X-API-KEY) contact-form endpoints.

Leaked widget keys are a known risk; without throttling they enable resource
exhaustion and quota burn on the upstream email/calendar APIs. The class-level
``fallback_rate`` is the safety net — a missing ``DEFAULT_THROTTLE_RATES``
entry must never produce an unthrottled endpoint.

No cache key ever holds key material. Both paths use the same two layers, so one person holding the public
widget key (it ships to every browser) cannot silence the shop's form for everyone: a per-visitor bucket at the
scope's rate, then a per-key ceiling (scope ``<scope>_token``, unconfigured 20 × the throttle's class
``fallback_rate``) that still caps a key replayed from many addresses. Access path (the key is an access token,
``request.access_token``): visitor bucket ``token:<pk>:<client ip>``, ceiling ``token:<pk>``. Legacy path: visitor
bucket ``<fingerprint>:<client ip>``, ceiling ``<fingerprint>``, the fingerprint being the first 16 hex chars of the
key's SHA-256. The ceiling counts only requests the visitor bucket let through — one address cannot spend it with
refused requests. The reverse asymmetry is deliberate: the visitor bucket records its hit before the ceiling is
consulted, so a request the ceiling refuses still spends that visitor's own allowance.

The client IP comes from ``django_utils.api.client_ip.get_client_ip``: ``settings.CLIENT_IP_HEADER`` (e.g.
``HTTP_CF_CONNECTING_IP``) when set and present, otherwise DRF's ``get_ident``, which trusts ``X-Forwarded-For``
unless ``NUM_PROXIES`` is set. A service behind a proxy MUST set one of the two; the ceiling is what holds when the
address is spoofed.

v1 and v2 submit are throttled independently (``contact_forms_submit_v1`` vs
``contact_forms_submit``): a burst on one API surface never spends the other's budget.

NOTE: the fallback must NOT live in a class-level ``rate`` attribute — DRF's
``SimpleRateThrottle.__init__`` only calls ``get_rate()`` when ``rate`` is
unset, so a class ``rate`` silently disables the ``DEFAULT_THROTTLE_RATES``
service override. ``__init__`` resolves the rate explicitly instead.
"""

from hashlib import sha256

from django_utils.api.client_ip import ClientIPThrottleMixin
from rest_framework.throttling import AnonRateThrottle

CEILING_FACTOR = 20


def key_fingerprint(key: str) -> str:
    """A key's bucket name on the legacy path: never the key itself."""
    return sha256(key.encode()).hexdigest()[:16]


def _key_ident(request) -> str | None:
    """The bucket name of the request's key: access token pk, else key fingerprint; None without a key."""
    if token := getattr(request, "access_token", None):
        return f"token:{token.pk}"
    key = request.headers.get("X-API-KEY")
    return key_fingerprint(key) if key else None


class _ScopedAnonThrottle(ClientIPThrottleMixin, AnonRateThrottle):
    fallback_rate = "60/hour"

    def __init__(self) -> None:
        # Resolve config-or-fallback BEFORE super().__init__ — DRF skips
        # get_rate() entirely when self.rate is already set.
        self.rate = self.get_rate()
        super().__init__()

    def get_rate(self) -> str:
        try:
            rate = super().get_rate()
        except Exception:  # noqa: BLE001 — DRF raises ImproperlyConfigured if scope unset
            return self.fallback_rate
        if not rate or "/" not in rate:  # malformed rate must not disable throttling
            return self.fallback_rate
        return rate


class _TokenCeilingThrottle(_ScopedAnonThrottle):
    """One bucket per key, across every visitor; unconfigured, 20 × the visitor throttle's class fallback."""

    def __init__(self, visitor_fallback_rate: str) -> None:
        count, period = visitor_fallback_rate.split("/", 1)
        self.fallback_rate = f"{int(count) * CEILING_FACTOR}/{period}"
        super().__init__()

    def get_cache_key(self, request, view) -> str:
        return self.cache_format % {"scope": self.scope, "ident": _key_ident(request)}


class _WidgetThrottle(_ScopedAnonThrottle):
    """Per key + client IP, then the key's ceiling."""

    ceiling: type[_TokenCeilingThrottle]
    _refused_by: _TokenCeilingThrottle | None = None

    def get_cache_key(self, request, view) -> str:
        ident = self.get_ident(request)
        if key_ident := _key_ident(request):
            ident = f"{key_ident}:{ident}"
        return self.cache_format % {"scope": self.scope, "ident": ident}

    def allow_request(self, request, view) -> bool:
        if not super().allow_request(request, view):
            return False
        if _key_ident(request) is None:
            return True
        ceiling = self.ceiling(self.fallback_rate)
        if ceiling.allow_request(request, view):
            return True
        self._refused_by = ceiling
        return False

    def wait(self) -> float | None:
        return self._refused_by.wait() if self._refused_by else super().wait()


class _SubmitCeiling(_TokenCeilingThrottle):
    scope = "contact_forms_submit_token"


class ContactFormSubmitThrottle(_WidgetThrottle):
    scope = "contact_forms_submit"
    fallback_rate = "30/hour"
    ceiling = _SubmitCeiling


class _SubmitV1Ceiling(_TokenCeilingThrottle):
    scope = "contact_forms_submit_v1_token"


class ContactFormSubmitV1Throttle(_WidgetThrottle):
    """v1 ``contact_form/`` routes: the same kind of throttle as v2 submit, in buckets of their own."""

    scope = "contact_forms_submit_v1"
    fallback_rate = "30/hour"
    ceiling = _SubmitV1Ceiling


class _FormTypeListCeiling(_TokenCeilingThrottle):
    scope = "contact_forms_form_types_token"


class FormTypeListThrottle(_WidgetThrottle):
    scope = "contact_forms_form_types"
    fallback_rate = "120/hour"
    ceiling = _FormTypeListCeiling


class _BookingCeiling(_TokenCeilingThrottle):
    scope = "contact_forms_booking_token"


class BookingThrottle(_WidgetThrottle):
    """Booking: per key + client address, under the key's ceiling.

    Without it a leaked booking key allows unbounded slot exhaustion + Google
    Calendar quota burn. Configure via ``DEFAULT_THROTTLE_RATES["contact_forms_booking"]``.
    """

    scope = "contact_forms_booking"
    fallback_rate = "10/hour"
    ceiling = _BookingCeiling
