# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Celery task: drain the OfflineConversionQueue per channel.

Lazy-imports the SDK so the module imports cleanly without the [google-ads]
extra installed. Schedule via Celery Beat in the consuming service:

    "contact-forms-upload-conversions": {
        "task": "django_contact_forms.tasks.upload_pending_conversions.upload_pending_conversions",
        "schedule": crontab(minute="*/5"),
        "options": {"queue": "contact_forms_conversions"},
    }
"""

from celery import shared_task
from process_logger import ProcessLogger

logger = ProcessLogger(process_name="upload_pending_conversions", module="django_contact_forms")


@shared_task(queue="contact_forms_conversions", bind=True, max_retries=3, default_retry_delay=300)
def upload_pending_conversions(self, channel_idx: str) -> dict:
    """Upload pending offline conversions for one channel. Returns counters for monitoring."""
    from django_contact_forms.services.conversions.google_ads_uploader import upload_pending

    try:
        outcome = upload_pending(channel_idx=channel_idx)
    except Exception as exc:
        logger.exception(exc)
        raise self.retry(exc=exc) from exc

    return {"channel_idx": channel_idx, "imported": outcome.imported, "failed": outcome.failed}
