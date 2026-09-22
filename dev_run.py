"""Local dry-run of the Phase A core without Zoho Desk/Azure access.

Feeds a canned ticket through the orchestrator so you can see the provisioning plan and
audit log. No network calls, no writes.

    python dev_run.py
"""

from __future__ import annotations

from lib.zoho import ZohoDeskClient


class CannedDesk(ZohoDeskClient):
    """Uses the REAL parse_ticket against a canned email-summary body; stubs the network."""

    def __init__(self, raw):
        super().__init__()
        self._raw = raw
        self.notes = []

    def get_ticket_raw(self, ticket_id):
        return self._raw

    def post_note(self, ticket_id, note):
        self.notes.append((ticket_id, note))
        print(f"\n--- NOTE posted to ticket {ticket_id} ---\n{note}\n")

    def update_status(self, ticket_id, status):
        print(f"--- STATUS ticket {ticket_id} -> {status} ---")


# A canned Zoho Forms ${zf:ALL_FIELDS} summary (the client maps to the example config).
DEV_SUMMARY = """
Company's Name : example-entra
New Starter's Name : Ms., Ada, Lovelace
New Starter's NS Email Address : ada.lovelace@acme.com
Job Title : Account Manager
Department : Sales
Country : United Kingdom
Start Date : 01-Oct-2026
"""


def main() -> None:
    from agent.orchestrator import process_ticket
    from lib.state import InMemoryState

    raw = {"id": "T-DEV-1", "subject": "New Starter Onboarding", "description": DEV_SUMMARY}
    process_ticket("T-DEV-1", desk=CannedDesk(raw), state=InMemoryState())


if __name__ == "__main__":
    main()
