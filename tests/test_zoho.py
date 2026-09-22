"""Zoho Desk client tests: field mapping (parse_ticket) + status mapping. No network.

These lock in the SHAPE of the Desk→Ticket mapping. The exact custom-field API names are
placeholders (see lib/zoho.py TODOs); update these tests alongside the real field names when
the Desk instance is wired up.
"""

from lib.ticket import TicketType
from lib.zoho import (
    STATUS_AWAITING_APPROVAL,
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_NEEDS_ATTENTION,
    STATUS_NAME_MAP,
    ZohoDeskClient,
)


def _raw(**overrides):
    raw = {
        "id": "1892000000123456",
        "ticketNumber": "101",
        "accountId": "1892000000042001",
        "cf": {
            "cf_request_type": "starter",
            "cf_first_name": "Ada",
            "cf_last_name": "Lovelace",
            "cf_job_title": "Account Manager",
            "cf_department": "Sales",
            "cf_role": "Sales",
            "cf_manager_email": "boss@example.com",
        },
    }
    raw.update(overrides)
    return raw


def test_parse_ticket_maps_custom_fields():
    ticket = ZohoDeskClient().parse_ticket(_raw())
    assert ticket.ticket_id == "1892000000123456"
    assert ticket.client_id == "1892000000042001"
    assert ticket.ticket_type is TicketType.STARTER
    assert ticket.starter is not None
    assert ticket.starter.first_name == "Ada"
    assert ticket.starter.last_name == "Lovelace"
    assert ticket.starter.role == "Sales"
    assert ticket.starter.manager_email == "boss@example.com"


def test_parse_ticket_uses_department_when_no_account():
    raw = _raw()
    del raw["accountId"]
    raw["departmentId"] = "1892000000999001"
    ticket = ZohoDeskClient().parse_ticket(raw)
    assert ticket.client_id == "1892000000999001"


def test_parse_ticket_leaver_has_no_starter_details():
    raw = _raw()
    raw["cf"]["cf_request_type"] = "leaver"
    ticket = ZohoDeskClient().parse_ticket(raw)
    assert ticket.ticket_type is TicketType.LEAVER
    assert ticket.starter is None


def test_parse_ticket_unknown_type_defaults_to_starter():
    raw = _raw()
    raw["cf"]["cf_request_type"] = "something-odd"
    ticket = ZohoDeskClient().parse_ticket(raw)
    assert ticket.ticket_type is TicketType.STARTER


def test_status_map_covers_all_logical_statuses():
    for status in (
        STATUS_AWAITING_APPROVAL,
        STATUS_COMPLETED,
        STATUS_FAILED,
        STATUS_NEEDS_ATTENTION,
    ):
        assert status in STATUS_NAME_MAP


def test_placeholder_credentials_do_no_network():
    # With placeholder creds, listing returns empty and writes are no-ops (no exception).
    client = ZohoDeskClient()
    assert client.list_open_starter_leaver_ticket_ids() == []
    client.post_note("1", "hello")  # prints, no raise
    client.update_status("1", STATUS_COMPLETED)  # prints, no raise
