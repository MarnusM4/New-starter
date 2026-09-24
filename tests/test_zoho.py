"""Zoho Desk client tests: email-summary intake parsing + status mapping. No network.

Flawless's onboarding requests arrive as a Zoho Forms ${zf:ALL_FIELDS} summary in the ticket
body (a `Label : Value` block). These lock in the SHAPE of that parse. The exact label
strings are Flawless-form-specific (see lib/zoho.DEFAULT_FIELD_LABELS); update alongside the
real labels when confirmed against a live ticket.
"""

import pytest

from lib import zoho
from lib.config import UnknownClientError, load_client, resolve_config
from lib.ticket import TicketType, split_person_name
from lib.zoho import (
    DEFAULT_FIELD_LABELS,
    STATUS_AWAITING_APPROVAL,
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_NEEDS_ATTENTION,
    STATUS_NAME_MAP,
    ZohoDeskClient,
    parse_summary,
)

# A realistic plain-text form summary (mirrors the sample ticket), company mapped to the
# self-referencing example config so resolve_config succeeds.
SUMMARY_BODY = """
Your name : Quinton, Miller
Your Email address : quintonm@naturalselection.travel
Consent to purchase new licences : Agreed
Company's Name : example-entra
New Starter's Name : Ms., Paula, Potgieter
New Starter's NS Email Address : paulap@naturalselection.travel
Job Title : Digital Marketing Manager
Department : Brand Communication
Country : South Africa
Start Date : 29-Sep-2026
Which department set-up should be configured on the device? : Marketing
"""


def _raw(body=SUMMARY_BODY, **overrides):
    raw = {"id": "1892000000123456", "subject": "New Starter Onboarding", "description": body}
    raw.update(overrides)
    return raw


def test_parse_ticket_from_email_summary():
    ticket = ZohoDeskClient().parse_ticket(_raw())
    assert ticket.ticket_id == "1892000000123456"
    assert ticket.client_id == "example-entra"
    assert ticket.ticket_type is TicketType.STARTER
    assert ticket.starter is not None
    assert ticket.starter.first_name == "Paula"
    assert ticket.starter.last_name == "Potgieter"
    assert ticket.starter.job_title == "Digital Marketing Manager"
    assert ticket.starter.department == "Brand Communication"
    assert ticket.starter.start_date == "29-Sep-2026"
    # NS email's local part becomes the intended login (domain comes from client config).
    assert ticket.starter.desired_username == "paulap"


def test_department_label_does_not_bleed_into_similar_line():
    # "Department : Brand Communication" must win over "Which department set-up...? : Marketing"
    ticket = ZohoDeskClient().parse_ticket(_raw())
    assert ticket.starter.department == "Brand Communication"


def test_parse_ticket_from_html_body():
    body = (
        "<div>Company's Name : example-entra<br>"
        "New Starter's Name : Mr., John, Smith<br>"
        "Job Title : Field Technician</div>"
    )
    ticket = ZohoDeskClient().parse_ticket(_raw(body=body))
    assert ticket.client_id == "example-entra"
    assert ticket.starter.first_name == "John"
    assert ticket.starter.last_name == "Smith"
    assert ticket.starter.job_title == "Field Technician"


def test_unknown_company_does_not_raise_here():
    # parse_ticket must not raise for an unidentified client — the orchestrator flags it later.
    body = SUMMARY_BODY.replace("example-entra", "Nonexistent Holdings Ltd")
    ticket = ZohoDeskClient().parse_ticket(_raw(body=body))
    assert ticket.client_id.startswith("unidentified:")
    assert "Nonexistent Holdings Ltd" in ticket.client_id
    with pytest.raises(UnknownClientError):
        resolve_config(ticket.client_id)


def test_leaver_subject_classifies_as_leaver():
    ticket = ZohoDeskClient().parse_ticket(_raw(subject="Leaver / Offboarding request"))
    assert ticket.ticket_type is TicketType.LEAVER
    assert ticket.starter is None


def test_per_client_field_labels_override(monkeypatch):
    cfg = load_client("example-entra").model_copy(update={"field_labels": {"job_title": "Position"}})
    monkeypatch.setattr(zoho, "resolve_config", lambda key: cfg)
    body = (
        "Company's Name : example-entra\n"
        "New Starter's Name : Ada, Lovelace\n"
        "Position : Analyst\n"
    )
    ticket = ZohoDeskClient().parse_ticket(_raw(body=body))
    assert ticket.starter.job_title == "Analyst"


def test_split_person_name_variants():
    assert split_person_name("Ms., Paula, Potgieter") == ("Ms.", "Paula", "Potgieter")
    assert split_person_name("Paula, Potgieter") == (None, "Paula", "Potgieter")
    assert split_person_name("Paula Potgieter") == (None, "Paula", "Potgieter")


def test_parse_summary_only_reads_whitelisted_labels():
    body = "Job Title : Analyst\nSecret : do-not-read\n"
    out = parse_summary(body, {"job_title": DEFAULT_FIELD_LABELS["job_title"]})
    assert out == {"job_title": "Analyst"}


def test_status_map_covers_all_logical_statuses():
    for status in (
        STATUS_AWAITING_APPROVAL,
        STATUS_COMPLETED,
        STATUS_FAILED,
        STATUS_NEEDS_ATTENTION,
    ):
        assert status in STATUS_NAME_MAP


def test_placeholder_credentials_do_no_network():
    client = ZohoDeskClient()
    assert client.list_open_starter_leaver_ticket_ids() == []
    client.post_note("1", "hello")  # prints, no raise
    client.update_status("1", STATUS_COMPLETED)  # prints, no raise


def test_desk_status_defaults_and_env_override(monkeypatch):
    from lib.zoho import desk_status_name

    monkeypatch.delenv("ZOHO_STATUS_NEEDS_ATTENTION", raising=False)
    assert desk_status_name(STATUS_NEEDS_ATTENTION) == "Needs Attention"
    assert desk_status_name(STATUS_FAILED) == "Automation Failed"
    monkeypatch.setenv("ZOHO_STATUS_NEEDS_ATTENTION", "Escalated - Automation")
    assert desk_status_name(STATUS_NEEDS_ATTENTION) == "Escalated - Automation"
