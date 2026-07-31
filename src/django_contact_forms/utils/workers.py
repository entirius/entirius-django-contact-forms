# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from django.core.exceptions import ObjectDoesNotExist
from django_regional.models import Language

from django_contact_forms.models import Channel


def get_language(request, channel: Channel, requested: str | None) -> (Language, str | None):
    """
    Get language from channel or default language if requested language is not supported
    :param request:
    :param channel:
    :param requested:
    :return:
    """
    requested = requested.lower() if isinstance(requested, str) else requested
    msg = None
    if requested is None:
        default_iso = channel.default_language.iso2 if channel.default_language else None
        msg = f"Requested language is not supported: {requested}. Using channel default: {default_iso}."
        requested = default_iso

    try:
        language = Language.objects.get(iso2=requested)
    except ObjectDoesNotExist:
        language = None
        msg = f"Requested language is not supported: {requested}."
    request.messages.append(msg)
    return language, msg
