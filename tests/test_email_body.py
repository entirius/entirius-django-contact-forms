# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Pure-Python tests for the email body formatter (no DB needed)."""

from django_contact_forms.utils.email_body import BodyRow, body_rows, body_text, humanize_key, stringify_value

SUBMISSION = {
    "name": "Lorem Ipsum",
    "email": "lorem.ipsum@example.com",
    "answer": "Lorem ipsum dolor sit amet,\nconsectetur adipiscing elit",
    "consent_age": True,
    "order_number": "0000000001",
    "consent_terms": True,
}


def test_body_rows_one_row_per_field_in_submission_order():
    rows = body_rows(SUBMISSION)

    assert [row.label for row in rows] == ["Name", "Email", "Answer", "Consent age", "Order number", "Consent terms"]
    assert rows[0] == BodyRow(label="Name", value="Lorem Ipsum")
    assert rows[4].value == "0000000001"


def test_body_rows_keeps_line_breaks_in_values():
    rows = body_rows(SUBMISSION)

    assert rows[2].value == "Lorem ipsum dolor sit amet,\nconsectetur adipiscing elit"


def test_body_rows_empty_body():
    assert body_rows(None) == []
    assert body_rows({}) == []
    assert body_rows("") == []


def test_body_rows_non_dict_body_is_single_unlabeled_row():
    assert body_rows("free text") == [BodyRow(label="", value="free text")]
    assert body_rows(["a", "b"]) == [BodyRow(label="", value='[\n  "a",\n  "b"\n]')]


def test_humanize_key():
    assert humanize_key("order_number") == "Order number"
    assert humanize_key("consent-age") == "Consent age"
    assert humanize_key("orderNumber") == "OrderNumber"
    assert humanize_key("email") == "Email"


def test_stringify_value():
    assert stringify_value(None) == ""
    assert stringify_value(True) == "yes"
    assert stringify_value(False) == "no"
    assert stringify_value(0) == "0"
    assert stringify_value(12.5) == "12.5"
    assert stringify_value({"city": "Zürich"}) == '{\n  "city": "Zürich"\n}'


def test_body_text_multiline_values_start_on_their_own_line():
    assert body_text(SUBMISSION) == (
        "Name: Lorem Ipsum\n"
        "Email: lorem.ipsum@example.com\n"
        "Answer:\n"
        "Lorem ipsum dolor sit amet,\n"
        "consectetur adipiscing elit\n"
        "Consent age: yes\n"
        "Order number: 0000000001\n"
        "Consent terms: yes"
    )


def test_body_text_empty_and_unlabeled():
    assert body_text(None) == ""
    assert body_text({}) == ""
    assert body_text("free text") == "free text"
