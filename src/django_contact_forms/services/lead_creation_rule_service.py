# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Rule lookup + attribution extraction for opt-in Lead creation on submit.

Parallel to ``notification_service.should_send_email``. The submit endpoint
calls ``should_create_lead`` after a ContactForm is saved; if it returns
``(True, source_type)``, the view extracts attribution from ``body`` and
delegates to ``lead_service.create_lead``.
"""

from django_contact_forms.models import Channel, Lead, LeadCreationRule


def should_create_lead(channel: Channel, form_type: str | None = None, slug: str | None = None) -> tuple[bool, str]:
    """Resolve whether a submission should spawn a Lead, and under which source_type.

    Fallback chain:
      1. exact(channel, type, slug)
      2. type-level(channel, type, "")
      3. channel-level(channel, "", "")
      4. off — no global default. Lead creation is opt-in only.

    A matched row stops the fallback even when ``enabled=False``, so an operator
    can park a "no leads from this slug" exception on top of a broader enabled
    rule. Default source_type when no match: ``"form"``.
    """
    form_type = form_type or ""
    slug = slug or ""

    # Try exact match first
    if form_type and slug:
        rule = _find_rule(channel, form_type, slug)
        if rule:
            return rule.enabled, rule.source_type

    # Try type-level
    if form_type:
        rule = _find_rule(channel, form_type, "")
        if rule:
            return rule.enabled, rule.source_type

    # Try channel-level
    rule = _find_rule(channel, "", "")
    if rule:
        return rule.enabled, rule.source_type

    return False, Lead.SourceType.FORM


def _find_rule(channel: Channel, form_type: str, slug: str) -> LeadCreationRule | None:
    return LeadCreationRule.objects.filter(channel=channel, form_type=form_type, slug=slug).first()


# Keys we pull off the submission body when creating a Lead. Anything not in
# this list stays in raw_data but does not get promoted to a dedicated column.
_CONTACT_KEYS = ("name", "phone", "company", "message")
_UTM_MAP = {
    "utm_campaign": "campaign_name",
    "utm_source": "source",
    "utm_medium": "medium",
}


def extract_attribution(body) -> dict:
    """Map a ContactForm.body dict to ``lead_service.create_lead`` kwargs.

    Best-effort: fields not present in body are omitted. Mirrors the shape
    used by ``booking_service._create_lead_for_booking``. Always includes
    ``raw_data`` (the full body, so nothing is lost) when body is a dict.

    If body is ``None`` or not a dict, returns ``{}`` — the resulting Lead
    carries only what's on ``ContactForm.email`` (handed in separately by
    the caller via the ``email=`` kwarg on ``lead_service.create_lead``).
    """
    if not isinstance(body, dict):
        return {}

    out: dict = {"raw_data": body}

    for key in _CONTACT_KEYS:
        value = body.get(key)
        if value is not None:
            out[key] = value

    gclid = body.get("gclid") or ""
    if gclid:
        out["gclid"] = gclid
        out["attribution_method"] = Lead.AttributionMethod.GCLID
    else:
        out["attribution_method"] = Lead.AttributionMethod.UNATTRIBUTED

    for body_key, lead_field in _UTM_MAP.items():
        value = body.get(body_key)
        if value is not None:
            out[lead_field] = value

    landing_page = body.get("landing_page")
    if landing_page is not None:
        out["landing_page"] = landing_page

    return out
