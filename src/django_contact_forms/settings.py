# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import os

from django.conf import settings

API_PUBLIC_BASE_URL = "/api/"
BASE_URL = API_PUBLIC_BASE_URL.strip("/")

# CUSTOM_FORM_ATTACHMENT FILES
PRIVATE_DIR = getattr(settings, "PRIVATE_DIR", None)
if not PRIVATE_DIR:
    raise OSError("Setting PRIVATE_DIR is not set. Default should be '/private'.")
CUSTOM_FORM_ATTACHMENT_DIR = os.path.join(PRIVATE_DIR, "contact_form_attachments/")

# Max size of json field in MB
FORMS_MAX_JSON_MB_SIZE = getattr(settings, "FORMS_MAX_JSON_MB_SIZE", 50)
FORMS_MAX_ATTACHMENT_MB_SIZE = getattr(settings, "FORMS_MAX_ATTACHMENT_MB_SIZE", 50)
FORMS_MAX_ATTACHMENT_COUNT = getattr(settings, "FORMS_MAX_ATTACHMENT_COUNT", 10)


DEFAULT_FROM_EMAIL_CONTACT_FORM = getattr(settings, "DEFAULT_FROM_EMAIL_CONTACT_FORM", None)
CONTACT_FORM_SEND_ADMIN_EMAIL = getattr(settings, "CONTACT_FORM_SEND_ADMIN_EMAIL", True)

# Form-type catalog: code used when a submission carries no type or one not
# configured for the channel, and no FormType is flagged is_default.
CONTACT_FORM_DEFAULT_TYPE = getattr(settings, "CONTACT_FORM_DEFAULT_TYPE", "default")
# Global fallback for sending the submitter a copy of the notification, used when
# no FormNotificationConfig matches. Per-config send_client_copy overrides this.
CONTACT_FORM_SEND_CLIENT_COPY = getattr(settings, "CONTACT_FORM_SEND_CLIENT_COPY", False)

# Email template paths + render live in django-email since 2.1.0 — see
# docs/multilang-emails.md. To override a template per deployment, set
# BOOKING_CONFIRMATION_EMAIL_TEMPLATE_PATH / BOOKING_ADMIN_NOTIFICATION_EMAIL_TEMPLATE_PATH
# / CONTACT_FORM_SUBMISSION_EMAIL_TEMPLATE_PATH in Django settings; django-email
# reads them via its own settings module.

EMAIL_BACKENDS_CHANNELS = getattr(settings, "EMAIL_BACKENDS_CHANNELS", None)

# Google Ads — deployment-wide secrets. Per-channel customer_id and refresh_token
# live on GoogleAdsConfig (DB), runtime-changeable. The kill-switches are on the
# ContactFormsSettings singleton (also DB).
GOOGLE_ADS_DEVELOPER_TOKEN = getattr(settings, "GOOGLE_ADS_DEVELOPER_TOKEN", "")
GOOGLE_ADS_OAUTH_CLIENT_ID = getattr(settings, "GOOGLE_ADS_OAUTH_CLIENT_ID", "")
GOOGLE_ADS_OAUTH_CLIENT_SECRET = getattr(settings, "GOOGLE_ADS_OAUTH_CLIENT_SECRET", "")
CONTACT_FORMS_CONVERSIONS_BATCH_SIZE = getattr(settings, "CONTACT_FORMS_CONVERSIONS_BATCH_SIZE", 100)

# Booking — service-account credentials lockdown. BookingConfig.clean() refuses
# any path that doesn't resolve under this directory. Defends against admin-set
# path traversal / file disclosure via the calendar credentials field.
CONTACT_FORMS_CREDENTIALS_DIR = getattr(settings, "CONTACT_FORMS_CREDENTIALS_DIR", "/app/credentials/")
