# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Context the contact-form task hands to django-email."""

from unittest.mock import patch

import pytest
from django.conf import settings
from django.test import override_settings

from django_contact_forms.models import ContactForm
from django_contact_forms.tasks.send_contact_form_email import _submission_context, send_contact_form_email
from django_contact_forms.utils.email_body import BodyRow
from tests.factories import ContactFormFactory

_SUBMISSION_EMAIL = "django_email.service.contact_forms.contact_form_submission.ContactFormSubmissionEmail"

SUBMISSION = {
    "name": "Lorem Ipsum",
    "email": "lorem.ipsum@example.com",
    "answer": "Lorem ipsum dolor sit amet,\nconsectetur adipiscing elit",
    "consent_age": True,
    "order_number": "0000000001",
    "consent_terms": True,
}


def test_submission_context_body_as_text_and_rows():
    contact_form = ContactForm(email="lorem.ipsum@example.com", type="contest", body=SUBMISSION)

    ctx = _submission_context(contact_form)

    assert ctx["form_email"] == "lorem.ipsum@example.com"
    assert ctx["form_type"] == "contest"
    assert ctx["form_slug"] == ""
    assert ctx["form_code"] == ""
    assert ctx["form_body"] == (
        "Name: Lorem Ipsum\nEmail: lorem.ipsum@example.com\nAnswer:\nLorem ipsum dolor sit amet,\n"
        "consectetur adipiscing elit\nConsent age: yes\nOrder number: 0000000001\nConsent terms: yes"
    )
    assert ctx["form_body_rows"][2] == BodyRow(
        label="Answer", value="Lorem ipsum dolor sit amet,\nconsectetur adipiscing elit"
    )
    assert "{" not in ctx["form_body"]  # no dict repr leaks into the email


def test_submission_context_empty_body_is_falsy():
    ctx = _submission_context(ContactForm(email="lorem@example.com", body=None))

    assert ctx["form_body"] == ""
    assert ctx["form_body_rows"] == []


@pytest.mark.django_db
@override_settings(INSTALLED_APPS=[*settings.INSTALLED_APPS, "django_email"])
def test_task_hands_readable_body_to_the_admin_notification():
    """End of the wire: what django-email receives for the operator inbox is the
    formatted text, not a JSON/dict dump of ``ContactForm.body``."""
    contact_form = ContactFormFactory(
        body={
            "order_number": "ENT-0042",
            "answer": "Kestrel Supply pallets,\nweekly delivery",
            "consent_age": True,
        }
    )

    with patch(_SUBMISSION_EMAIL) as submission_email:
        send_contact_form_email(contact_form.pk, "ops@novatrade.example.com")

    submission_email.return_value.send.assert_called_once()
    form_body = submission_email.return_value.send.call_args.kwargs["submission_context"]["form_body"]
    assert "Order number: ENT-0042" in form_body
    assert "Answer:\nKestrel Supply pallets,\nweekly delivery" in form_body
    assert "Consent age: yes" in form_body
    assert "{" not in form_body
