"""Zoho Desk API client (Phase A).

Replaces the earlier HALO PSA client: Zoho Desk is now the ticketing system that drives
starter/leaver provisioning. A Desk ticket (or a Desk workflow rule) fires the webhook;
this client reads the ticket, posts the plan/result back as a comment, and moves the
ticket's status.

PLACEHOLDER: the real custom-field ids, the starter/leaver classifier field, the status
names, and the open-ticket filter are specific to the client's Desk instance and are not
known yet. The methods below have the right SHAPE and are wired into the orchestrator, but
network calls are guarded so nothing breaks before API access exists. Fill in the TODOs
once you have Zoho Desk API credentials and the field mapping.

Auth model (differs from HALO): Zoho uses OAuth2 with a long-lived **refresh token**
(created once via a self-client / authorised grant). At call time we exchange the refresh
token for a short-lived access token against the regional `accounts.zoho.*` endpoint, then
call the regional `desk.zoho.*` API with `Authorization: Zoho-oauthtoken <token>` and the
`orgId` header. Pick the domains for your data-centre region (see ZOHO_*_URL below):
  US  desk.zoho.com     accounts.zoho.com
  EU  desk.zoho.eu      accounts.zoho.eu
  IN  desk.zoho.in      accounts.zoho.in
  AU  desk.zoho.com.au  accounts.zoho.com.au
"""

from __future__ import annotations

import os
import time
from typing import Any

import requests

from .retry import with_retries
from .ticket import StarterDetails, Ticket, TicketType


class ZohoDeskClient:
    def __init__(self) -> None:
        # Pulled from env / Key Vault. See .env.example.
        self.base_url = os.environ.get("ZOHO_DESK_BASE_URL", "https://desk.zoho.com")
        self.accounts_url = os.environ.get("ZOHO_ACCOUNTS_URL", "https://accounts.zoho.com")
        self.org_id = os.environ.get("ZOHO_ORG_ID", "PLACEHOLDER_ORG_ID")
        self.client_id = os.environ.get("ZOHO_CLIENT_ID", "PLACEHOLDER_CLIENT_ID")
        self.client_secret = os.environ.get("ZOHO_CLIENT_SECRET", "PLACEHOLDER_SECRET")
        # Long-lived refresh token minted once for this integration.
        self.refresh_token = os.environ.get("ZOHO_REFRESH_TOKEN", "PLACEHOLDER_REFRESH_TOKEN")
        self._token: str | None = None
        self._token_expiry: float = 0.0

    def _is_placeholder(self) -> bool:
        """No real credentials yet. Keeps dev runs from hitting live/fake endpoints."""
        return self.refresh_token.startswith("PLACEHOLDER") or self.client_secret.startswith(
            "PLACEHOLDER"
        )

    # ------------------------------------------------------------------ auth
    def _get_token(self) -> str:
        """OAuth2 access token via the refresh-token grant.

        Access tokens are short-lived (~1h); cache until shortly before expiry and refresh.
        TODO: confirm the token endpoint path/params for your region if Zoho changes them.
        """
        if self._token and time.time() < self._token_expiry:
            return self._token
        if self._is_placeholder():
            # No real creds yet — fail loudly rather than hitting a fake endpoint.
            raise RuntimeError(
                "Zoho credentials are placeholders; set them in .env / Key Vault"
            )

        resp = requests.post(
            f"{self.accounts_url}/oauth/v2/token",
            params={
                "grant_type": "refresh_token",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "refresh_token": self.refresh_token,
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        self._token = data["access_token"]
        # Refresh a minute early to avoid using a token that expires mid-request.
        self._token_expiry = time.time() + int(data.get("expires_in", 3600)) - 60
        return self._token

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Zoho-oauthtoken {self._get_token()}",
            "orgId": self.org_id,
        }

    # ------------------------------------------------------------------ reads
    def get_ticket_raw(self, ticket_id: str) -> dict[str, Any]:
        """Fetch the raw ticket JSON.

        TODO: confirm whether the starter custom fields come back by default or need
        `?include=` (Desk returns custom fields under the `cf` object).
        """
        def call() -> dict[str, Any]:
            resp = requests.get(
                f"{self.base_url}/api/v1/tickets/{ticket_id}",
                headers=self._headers(),
                timeout=30,
            )
            resp.raise_for_status()
            return resp.json()

        return with_retries(call)

    def list_open_starter_leaver_ticket_ids(self) -> list[str]:
        """Ticket ids of currently-open starter/leaver tickets (for the reconciliation poll).

        TODO: confirm the real filter. Options in Desk: a saved custom View id
        (GET /api/v1/tickets?viewId=...), or GET /api/v1/tickets with a status filter plus a
        category/classification/custom-field filter. Returning open (not yet completed)
        tickets lets the poll re-drive anything the webhook missed; idempotency stops double
        work.
        """
        if self._is_placeholder():
            print("[ZOHO PLACEHOLDER] would list open starter/leaver tickets")
            return []

        def call() -> list[str]:
            resp = requests.get(
                f"{self.base_url}/api/v1/tickets",
                headers=self._headers(),
                params={"status": "Open", "limit": 100},  # TODO: real starter/leaver filter
                timeout=30,
            )
            resp.raise_for_status()
            return [str(t["id"]) for t in resp.json().get("data", [])]

        return with_retries(call)

    def parse_ticket(self, raw: dict[str, Any]) -> Ticket:
        """Map the raw Zoho Desk payload to our normalised Ticket.

        PLACEHOLDER MAPPING: replace the keys below with the real Desk custom-field API
        names for your instance. Desk custom fields arrive under `cf` keyed by their API
        name (e.g. `cf_first_name`). Only these validated fields are used downstream — raw
        text is never executed as instructions.
        """
        cf = raw.get("cf", {}) or {}

        # TODO: real classifier. Desk has no built-in starter/leaver type — expect a custom
        # field (e.g. cf_request_type) or the ticket `classification`/`category`.
        raw_type = str(
            cf.get("cf_request_type") or raw.get("classification") or "starter"
        ).lower()
        ticket_type = TicketType(raw_type) if raw_type in TicketType._value2member_map_ else TicketType.STARTER

        # TODO: real client mapping key. Prefer a stable id (accountId / departmentId) over
        # a display name so the lookup survives a client rename.
        client_id = str(raw.get("accountId") or raw.get("departmentId") or "example-entra")

        starter = None
        if ticket_type is TicketType.STARTER:
            starter = StarterDetails(
                first_name=cf.get("cf_first_name", ""),
                last_name=cf.get("cf_last_name", ""),
                display_name=cf.get("cf_display_name"),
                job_title=cf.get("cf_job_title"),
                department=cf.get("cf_department"),
                role=cf.get("cf_role"),
                manager_email=cf.get("cf_manager_email"),
                desired_username=cf.get("cf_desired_username"),
                start_date=cf.get("cf_start_date"),
            )

        return Ticket(
            ticket_id=str(raw.get("id", ticket_id_fallback(raw))),
            client_id=client_id,
            ticket_type=ticket_type,
            starter=starter,
        )

    # ------------------------------------------------------------------ writes
    def post_note(self, ticket_id: str, note: str) -> None:
        """Append a comment to the ticket (used to post the provisioning plan / results).

        Posts a private (internal) comment by default so plan detail isn't exposed to the
        requester. TODO: confirm you want isPublic=false for your workflow.
        """
        if self._is_placeholder():
            # Dev mode: don't pretend to write. Surface what we'd send.
            print(f"[ZOHO PLACEHOLDER] would post comment to ticket {ticket_id}:\n{note}")
            return

        def call() -> None:
            requests.post(
                f"{self.base_url}/api/v1/tickets/{ticket_id}/comments",
                headers=self._headers(),
                json={"content": note, "isPublic": False},
                timeout=30,
            ).raise_for_status()

        with_retries(call)

    def update_status(self, ticket_id: str, status: str) -> None:
        """Move the ticket to a new status.

        Zoho Desk statuses are **named** strings (unlike HALO's numeric ids). Map our
        logical status names (see STATUS_NAME_MAP) to the real Desk status names configured
        for your instance before going live.
        """
        desk_status = STATUS_NAME_MAP.get(status, status)
        if self._is_placeholder():
            print(f"[ZOHO PLACEHOLDER] would set ticket {ticket_id} status -> {status} ({desk_status})")
            return

        def call() -> None:
            requests.patch(
                f"{self.base_url}/api/v1/tickets/{ticket_id}",
                headers=self._headers(),
                json={"status": desk_status},
                timeout=30,
            ).raise_for_status()

        with_retries(call)


# Logical status names used by the orchestrator. TODO: replace values with the real Zoho
# Desk status names configured for your instance. Desk ships with "Open"/"On Hold"/"Closed"
# by default; add custom statuses (e.g. "Awaiting Approval", "Provisioned") in Desk and map
# them here.
STATUS_AWAITING_APPROVAL = "awaiting_approval"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"
STATUS_NEEDS_ATTENTION = "needs_attention"

STATUS_NAME_MAP: dict[str, str] = {
    STATUS_AWAITING_APPROVAL: "PLACEHOLDER_STATUS_AWAITING",
    STATUS_COMPLETED: "PLACEHOLDER_STATUS_COMPLETED",
    STATUS_FAILED: "PLACEHOLDER_STATUS_FAILED",
    STATUS_NEEDS_ATTENTION: "PLACEHOLDER_STATUS_NEEDS_ATTENTION",
}


def ticket_id_fallback(raw: dict[str, Any]) -> str:
    return str(raw.get("ticketNumber", "UNKNOWN"))
