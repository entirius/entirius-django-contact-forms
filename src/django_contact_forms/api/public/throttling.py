# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Throttles for the public (X-API-KEY) contact-form endpoints.

Leaked widget keys are a known risk; without throttling they enable resource
exhaustion and quota burn on the upstream email/calendar APIs. The class-level
``fallback_rate`` is the safety net — a missing ``DEFAULT_THROTTLE_RATES``
entry must never produce an unthrottled endpoint.

NOTE: the fallback must NOT live in a class-level ``rate`` attribute — DRF's
``SimpleRateThrottle.__init__`` only calls ``get_rate()`` when ``rate`` is
unset, so a class ``rate`` silently disables the ``DEFAULT_THROTTLE_RATES``
service override. ``__init__`` resolves the rate explicitly instead.
"""

from rest_framework.throttling import AnonRateThrottle


class _ScopedAnonThrottle(AnonRateThrottle):
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

    def get_cache_key(self, request, view) -> str:
        # Key the bucket by API key, not client IP. APIKeyAuthentication leaves
        # request.user as AnonymousUser, so the default AnonRateThrottle would
        # bucket by IP — which neither caps a leaked key replayed from many IPs
        # (the threat this throttle exists for) nor spares clients behind shared
        # NAT. The X-API-KEY value is already a hash, safe to use as the ident.
        ident = request.headers.get("X-API-KEY") or self.get_ident(request)
        return self.cache_format % {"scope": self.scope, "ident": ident}


class ContactFormSubmitThrottle(_ScopedAnonThrottle):
    scope = "contact_forms_submit"
    fallback_rate = "30/hour"


class FormTypeListThrottle(_ScopedAnonThrottle):
    scope = "contact_forms_form_types"
    fallback_rate = "120/hour"
