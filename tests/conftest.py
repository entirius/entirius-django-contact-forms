# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import os
import secrets

import django
import pytest
from django.conf import settings

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tests.settings")


def pytest_configure():
    if not settings.configured:
        django.setup()


SUBMIT_SCOPE = "contact_forms.submit"
BOOKING_SCOPE = "contact_forms.booking"


@pytest.fixture
def make_api_key(db):
    """Create an X-API-KEY the module accepts today and return its raw value.

    ``scope``: ``BOOKING_SCOPE`` → a ``booking`` key, anything else → a ``contact_form`` key. The key contract
    tests go through this helper only, so moving the checks onto another key store changes this function, never
    the assertions. Values are random and never printed.
    """
    from django_contact_forms.models import APIKey

    def make_api_key(channel=None, scope: str | None = None) -> str:
        model_scope = APIKey.Scope.BOOKING if scope == BOOKING_SCOPE else APIKey.Scope.CONTACT_FORM
        raw = secrets.token_hex(32)
        APIKey.objects.create(channel=channel, key=raw, scope=model_scope)
        return raw

    return make_api_key
