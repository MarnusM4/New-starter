"""Local dry-run of the Phase A core without Zoho Desk/Azure access.

Feeds a canned ticket through the orchestrator so you can see the provisioning plan and
audit log. No network calls, no writes.

    python dev_run.py
"""

from __future__ import annotations

from lib.ticket import StarterDetails, Ticket, TicketType


class CannedDesk:
    def __init__(self, raw):
        self._raw = raw
        self.notes = []

    def get_ticket_raw(self, ticket_id):
        return self._raw

    def parse_ticket(self, raw):
        return Ticket(
            ticket_id=raw["id"],
            client_id=raw["client_ref"],
            ticket_type=TicketType(raw["type"]),
            starter=StarterDetails(**raw["user_info"]),
        )

    def post_note(self, ticket_id, note):
        self.notes.append((ticket_id, note))
        print(f"\n--- NOTE posted to ticket {ticket_id} ---\n{note}\n")

    def update_status(self, ticket_id, status):
        print(f"--- STATUS ticket {ticket_id} -> {status} ---")


def main() -> None:
    from agent.orchestrator import process_ticket
    from lib.state import InMemoryState

    raw = {
        "id": "T-DEV-1",
        "client_ref": "example-entra",
        "type": "starter",
        "user_info": {
            "first_name": "Ada",
            "last_name": "Lovelace",
            "job_title": "Account Manager",
            "role": "Sales",
            "manager_email": "boss@example.com",
        },
    }
    process_ticket("T-DEV-1", desk=CannedDesk(raw), state=InMemoryState())


if __name__ == "__main__":
    main()
