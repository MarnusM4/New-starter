"""HALO PSA API client (Phase A).

PLACEHOLDER: real endpoints, auth scopes, custom-field ids, and the user-info table
shape are not known yet. The methods below have the right SHAPE and are wired into the
orchestrator, but network calls are stubbed / guarded so nothing breaks before API
access exists. Fill in the TODOs once you have HALO API credentials and field mappings.
"""

from __future__ import annotations

import os
from typing import Any

import requests

from .retry import with_retries
from .ticket import StarterDetails, Ticket, TicketType


class HaloClient:
    def __init__(self) -> None:
        # Pulled from env / Key Vault. See .env.example.
        self.base_url = os.environ.get("HALO_BASE_URL", "https://PLACEHOLDER.halopsa.com")
        self.auth_url = os.environ.get("HALO_AUTH_URL", f"{self.base_url}/auth/token")
        self.client_id = os.environ.get("HALO_CLIENT_ID", "PLACEHOLDER_CLIENT_ID")
        self.client_secret = os.environ.get("HALO_CLIENT_SECRET", "PLACEHOLDER_SECRET")
        self.scope = os.environ.get("HALO_SCOPE", "all")
        self._token: str | None = None

    # ------------------------------------------------------------------ auth
    def _get_token(self) -> str:
        """OAuth2 client-credentials token.

        TODO: confirm HALO's token endpoint + body once API access is granted.
        """
        if self._token:
            return self._token
        if self.client_secret.startswith("PLACEHOLDER"):
            # No real creds yet — fail loudly rather than hitting a fake endpoint.
            raise RuntimeError("HALO credentials are placeholders; set them in .env / Key Vault")

        resp = requests.post(
            self.auth_url,
            data={
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "scope": self.scope,
            },
            timeout=30,
        )
        resp.raise_for_status()
        self._token = resp.json()["access_token"]
        return self._token

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._get_token()}"}

    # ------------------------------------------------------------------ reads
    def get_ticket_raw(self, ticket_id: str) -> dict[str, Any]:
        """Fetch the raw ticket JSON.

        TODO: confirm path (likely GET /api/Tickets/{id}) and whether the user-info
        table comes back inline or needs a second call.
        """
        def call() -> dict[str, Any]:
            resp = requests.get(
                f"{self.base_url}/api/Tickets/{ticket_id}", headers=self._headers(), timeout=30
            )
            resp.raise_for_status()
            return resp.json()

        return with_retries(call)

    def list_open_starter_leaver_ticket_ids(self) -> list[str]:
        """Ticket ids of currently-open starter/leaver tickets (for the reconciliation poll).

        TODO: confirm the real filter — likely GET /api/Tickets with a tickettype filter
        and an open-status filter, paged. Returning open (not yet completed) tickets lets
        the poll re-drive anything the webhook missed; idempotency stops double work.
        """
        if self.client_secret.startswith("PLACEHOLDER"):
            print("[HALO PLACEHOLDER] would list open starter/leaver tickets")
            return []
        def call() -> list[str]:
            resp = requests.get(
                f"{self.base_url}/api/Tickets",
                headers=self._headers(),
                params={"tickettype": "starter,leaver", "open_only": True},  # TODO: real params
                timeout=30,
            )
            resp.raise_for_status()
            return [str(t["id"]) for t in resp.json().get("tickets", [])]

        return with_retries(call)

    def parse_ticket(self, raw: dict[str, Any]) -> Ticket:
        """Map the raw HALO payload to our normalised Ticket.

        PLACEHOLDER MAPPING: replace the keys below with the real HALO field ids /
        custom-field names for your instance. Only these validated fields are used
        downstream — raw text is never executed as instructions.
        """
        # TODO: real field mapping. These keys are illustrative placeholders.
        ticket_type = TicketType(str(raw.get("type", "starter")).lower())
        client_id = str(raw.get("client_ref", "example-entra"))

        starter = None
        if ticket_type is TicketType.STARTER:
            fields = raw.get("user_info", {})  # TODO: real custom-field table location
            starter = StarterDetails(
                first_name=fields.get("first_name", ""),
                last_name=fields.get("last_name", ""),
                display_name=fields.get("display_name"),
                job_title=fields.get("job_title"),
                department=fields.get("department"),
                role=fields.get("role"),
                manager_email=fields.get("manager_email"),
                desired_username=fields.get("desired_username"),
                start_date=fields.get("start_date"),
            )

        return Ticket(
            ticket_id=str(raw.get("id", ticket_id_fallback(raw))),
            client_id=client_id,
            ticket_type=ticket_type,
            starter=starter,
        )

    # ------------------------------------------------------------------ writes
    def post_note(self, ticket_id: str, note: str) -> None:
        """Append a note to the ticket (used to post the provisioning plan / results).

        TODO: confirm the actions/notes endpoint shape.
        """
        if self.client_secret.startswith("PLACEHOLDER"):
            # Dev mode: don't pretend to write. Surface what we'd send.
            print(f"[HALO PLACEHOLDER] would post note to ticket {ticket_id}:\n{note}")
            return
        def call() -> None:
            requests.post(
                f"{self.base_url}/api/Actions",
                headers=self._headers(),
                json={"ticket_id": ticket_id, "note": note},  # TODO: real body
                timeout=30,
            ).raise_for_status()

        with_retries(call)

    def update_status(self, ticket_id: str, status: str) -> None:
        """Move the ticket to a new status.

        PLACEHOLDER: HALO statuses are numeric status ids. Map our logical status names
        (see STATUS_ID_MAP) to the real ids for your instance before going live.
        """
        status_id = STATUS_ID_MAP.get(status, status)
        if self.client_secret.startswith("PLACEHOLDER"):
            print(f"[HALO PLACEHOLDER] would set ticket {ticket_id} status -> {status} ({status_id})")
            return
        def call() -> None:
            requests.post(
                f"{self.base_url}/api/Tickets",
                headers=self._headers(),
                json={"id": ticket_id, "status_id": status_id},  # TODO: confirm body/field
                timeout=30,
            ).raise_for_status()

        with_retries(call)


# Logical status names used by the orchestrator. TODO: replace values with the real HALO
# numeric status ids for your instance.
STATUS_AWAITING_APPROVAL = "awaiting_approval"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"
STATUS_NEEDS_ATTENTION = "needs_attention"

STATUS_ID_MAP: dict[str, str] = {
    STATUS_AWAITING_APPROVAL: "PLACEHOLDER_STATUS_ID_AWAITING",
    STATUS_COMPLETED: "PLACEHOLDER_STATUS_ID_COMPLETED",
    STATUS_FAILED: "PLACEHOLDER_STATUS_ID_FAILED",
    STATUS_NEEDS_ATTENTION: "PLACEHOLDER_STATUS_ID_NEEDS_ATTENTION",
}


def ticket_id_fallback(raw: dict[str, Any]) -> str:
    return str(raw.get("ticket_id", "UNKNOWN"))
