# entirius-django-contact-forms

A Django module for contact forms in Entirius, the open-source modular ecommerce platform. It accepts form
submissions with attachments per sales channel, sends notification emails, takes calendar bookings, and turns
submissions into leads that can be reported to Google Ads as offline conversions.

[![PyPI](https://img.shields.io/pypi/v/entirius-django-contact-forms.svg)](https://pypi.org/project/entirius-django-contact-forms/)
[![Python](https://img.shields.io/pypi/pyversions/entirius-django-contact-forms.svg)](https://pypi.org/project/entirius-django-contact-forms/)
[![License: MPL-2.0](https://img.shields.io/badge/license-MPL--2.0-blue.svg)](https://github.com/entirius/entirius-django-contact-forms/blob/develop/LICENSE)

## What it does

- Accepts form submissions with file attachments, scoped per sales channel and typed from a per-channel catalog.
- Sends a notification to the shop and an optional copy to the submitter, configured per form type.
- Offers a booking calendar with free slots, backed by Google Calendar or a local-only backend.
- Creates leads from submissions and bookings and tracks them through a status pipeline.
- Uploads lead conversions to Google Ads.
- Exposes an admin API for the CMS and a key-protected, throttled public API for the storefront.

## Installation

```shell
uv add entirius-django-contact-forms
pip install entirius-django-contact-forms
```

```python
INSTALLED_APPS = [
    ...
    "django_regional",
    "django_utils",
    "django_contact_forms",
]

PRIVATE_DIR = "/private"  # required: root of the private file storage (attachments)

# urls.py
urlpatterns = [
    path("", include("django_contact_forms.urls")),
]
```

`PRIVATE_DIR` is the only required setting. Reference with defaults:
https://github.com/entirius/entirius-django-contact-forms/blob/develop/docs/configuration.md

Extras: `bookings` (Google Calendar backend for bookings), `google-ads` (conversion uploads), `email` (branded
notification emails through `entirius-django-email`).

```shell
uv add "entirius-django-contact-forms[bookings,google-ads,email]"
```

The public API takes a key in the `X-API-KEY` header. Where `django_access` is installed the key is an access token
with the scope `contact_forms.submit` (bookings: `contact_forms.booking`):

```shell
python manage.py access_token create --application storefront --create-application --scope contact_forms.submit --channel default
```

Without `django_access`, `python manage.py forms-generate-api-key` creates the key.

## Quick start

```python
from django_contact_forms.services.contact_form_service import create_submission, get_channel

channel = get_channel(idx="default")
form = create_submission(email="customer@example.com", channel=channel, body={"message": "Hello"})
```

## Requirements

- Python 3.11 or newer, Django 4.0 or newer.
- PostgreSQL, and Celery for email dispatch and conversion uploads.
- Entirius packages pulled in: `entirius-django-regional`, `entirius-django-utils`, `entirius-py-idx-normalizator`,
  `entirius-py-process-logger`.
- Optional, through the extras: `entirius-py-google-calendar-sdk`, `entirius-py-google-ads-sdk`,
  `entirius-django-email`.

## Documentation

- Module docs: https://github.com/entirius/entirius-django-contact-forms/tree/develop/docs
- Entirius documentation: https://docs.entirius.com/
- Changelog: https://github.com/entirius/entirius-django-contact-forms/blob/develop/CHANGELOG.md

## Part of Entirius

This module runs inside the Entirius backend service (Volkanos) and serves the forms of the storefront.

- Backend service: https://github.com/entirius/entirius-service-volkanos
- Docker harness: https://github.com/entirius/entirius-zeno
- Sibling modules: https://github.com/entirius/entirius-django-email, https://github.com/entirius/entirius-django-regional,
  https://github.com/entirius/entirius-django-access

## Development

```shell
make install     # sync dependencies (uv)
make check       # lint + format check (ruff)
make test        # test suite (pytest, needs PostgreSQL via DATABASE_URL)
```

Development and agent instructions: https://github.com/entirius/entirius-django-contact-forms/blob/develop/AGENTS.md

## License

Mozilla Public License 2.0 (MPL-2.0) — see https://github.com/entirius/entirius-django-contact-forms/blob/develop/LICENSE.
