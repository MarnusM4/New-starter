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
    cfg = load_client("example-entra").model_copy(update={"field_labels": {"job_title": "Role Title"}})
    monkeypatch.setattr(zoho, "resolve_config", lambda key: cfg)
    body = (
        "Company's Name : example-entra\n"
        "New Starter's Name : Ada, Lovelace\n"
        "Role Title : Analyst\n"
    )
    ticket = ZohoDeskClient().parse_ticket(_raw(body=body))
    assert ticket.starter.job_title == "Analyst"


def test_split_person_name_variants():
    assert split_person_name("Ms., Paula, Potgieter") == ("Ms.", "Paula", "Potgieter")
    assert split_person_name("Paula, Potgieter") == (None, "Paula", "Potgieter")
    assert split_person_name("Paula Potgieter") == (None, "Paula", "Potgieter")
    # Free-text "Name & Surname": everything after the first word is the surname.
    assert split_person_name("Marnus van den Heever") == (None, "Marnus", "van den Heever")
    assert split_person_name("Mr Raymond Young") == ("Mr", "Raymond", "Young")
    assert split_person_name("Dr., Jan, du Plessis") == ("Dr.", "Jan", "du Plessis")
    assert split_person_name("Ada") == (None, "Ada", "")


def test_family_wealth_form_parses_without_client_setup():
    from tests.test_run_ticket import FAMILY_WEALTH

    raw = _raw(body=FAMILY_WEALTH, subject="Family Wealth New User Onboarding Form - Raymond Young")
    ticket = ZohoDeskClient().parse_ticket(raw)
    assert ticket.ticket_type is TicketType.STARTER
    assert (ticket.starter.first_name, ticket.starter.last_name) == ("Raymond", "Young")
    assert ticket.starter.desired_username == "raymond.young"
    assert ticket.starter.start_date == "01-Nov-2026"
    assert ticket.starter.job_title == "Financial Planner"


def test_label_matching_is_tolerant():
    body = "new user\u2019s name and surname : Ada Lovelace\nJOB TITLE: Analyst\n"
    out = parse_summary(body, {"new_starter_name": DEFAULT_FIELD_LABELS["new_starter_name"],
                               "job_title": DEFAULT_FIELD_LABELS["job_title"]})
    assert out == {"new_starter_name": "Ada Lovelace", "job_title": "Analyst"}


def test_multiword_surname_username():
    from agent.orchestrator import build_plan
    from lib.config import load_client

    body = "Company's Name : example-entra\nNew Users Name & Surname : Marnus van den Heever\n"
    ticket = ZohoDeskClient().parse_ticket(_raw(body=body, subject="New User Onboarding"))
    plan = build_plan(ticket, load_client("example-entra"))
    assert plan.username == "marnus.vandenheever"
    assert plan.display_name == "Marnus van den Heever"


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


# Natural Selection's form as the client forwards it from Outlook: the summary table is
# rebuilt with every cell's text in its own <p>, nested inside a layout table.
OUTLOOK_FORWARD = """
<div><p>From: Quinton Miller<br>Subject: Natural Selection New Starter - Paula Potgieter</p></div>
<table class="MsoNormalTable"><tr><td>
 <p class="MsoNormal">Please find attached the New Starter Form for: Paula Potgieter</p>
 <table class="MsoNormalTable" cellpadding="0">
  <tr><td><p class="MsoNormal"><span>Your name</span></p></td>
      <td><p class="MsoNormal"><span>:</span></p></td>
      <td><p class="MsoNormal"><span>Quinton, Miller</span></p></td></tr>
  <tr><td><p class="MsoNormal">New Starter&#8217;s Name</p></td><td><p>:</p></td>
      <td><p class="MsoNormal">Ms., Paula, Potgieter</p></td></tr>
  <tr><td><p>New Starter&#8217;s NS Email Address</p></td><td><p>:</p></td>
      <td><p><a href="mailto:paulap@naturalselection.travel">paulap@naturalselection.travel</a></p></td></tr>
  <tr><td><p>Job Title</p></td><td><p>:</p></td><td><p>Digital <b>Marketing</b><br>Manager</p></td></tr>
  <tr><td><p>Start Date:</p></td><td><p>29-Sep-2026</p></td></tr>
 </table>
</td></tr></table>
"""


def test_outlook_forwarded_form_parses():
    raw = _raw(body=OUTLOOK_FORWARD,
               subject="Fw: Natural Selection New Starter - Paula Potgieter - APPROVAL NEEDED")
    ticket = ZohoDeskClient().parse_ticket(raw)
    assert ticket.ticket_type is TicketType.STARTER
    assert (ticket.starter.first_name, ticket.starter.last_name) == ("Paula", "Potgieter")
    assert ticket.starter.desired_username == "paulap"
    assert ticket.starter.job_title == "Digital Marketing Manager"   # multi-line cell joined
    assert ticket.starter.start_date == "29-Sep-2026"                # 2-column row, "Label:"
