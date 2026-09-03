# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Turn a submission ``body`` (free-form JSON from the storefront form) into
rows a human can read in the admin notification email.

Keys are arbitrary form field names, so labels are humanized keys
(``order_number`` -> ``Order number``); there is no per-form label mapping.
"""

import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class BodyRow:
    label: str
    value: str


def humanize_key(key: str) -> str:
    label = key.replace("_", " ").replace("-", " ").strip()
    return label[:1].upper() + label[1:]


def stringify_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, dict | list):
        return json.dumps(value, ensure_ascii=False, indent=2)
    return str(value)


def body_rows(body: Any) -> list[BodyRow]:
    """One row per top-level field, in submission order.

    A non-dict body (bare string, list) becomes a single unlabeled row.
    Line breaks inside values are kept verbatim; templates decide how to
    render them (``linebreaksbr`` in HTML).
    """
    if not body:
        return []
    if not isinstance(body, dict):
        return [BodyRow(label="", value=stringify_value(body))]
    return [BodyRow(label=humanize_key(str(key)), value=stringify_value(value)) for key, value in body.items()]


def body_text(body: Any) -> str:
    """Plain-text rendering: ``Label: value`` per line; multi-line values start
    on their own line so paragraphs survive ``<pre>`` blocks and text templates."""
    lines = []
    for row in body_rows(body):
        if not row.label:
            lines.append(row.value)
        elif "\n" in row.value:
            lines.append(f"{row.label}:\n{row.value}")
        else:
            lines.append(f"{row.label}: {row.value}")
    return "\n".join(lines)
