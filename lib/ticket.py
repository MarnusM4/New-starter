"""Normalised representation of a starter/leaver ticket.

The raw Zoho Desk payload is messy and client-specific. We parse it once into this typed
model and ONLY use these validated fields downstream. Raw ticket text is treated as
untrusted data, never as instructions (prompt-injection defence).
"""

from __future__ import annotations

import re
from enum import Enum

from pydantic import BaseModel, Field, field_validator


class InvalidTicketData(Exception):
    """A ticket-derived value failed validation at the trust boundary.

    Raised when untrusted ticket content can't be safely turned into a provisioning
    parameter (e.g. an out-of-policy username). The orchestrator catches this and flags
    the ticket for a human rather than provisioning something unexpected.
    """


# Usernames flow into UPNs, samAccountNames and OData filters. Allow only a conservative
# set so untrusted ticket input can't smuggle in separators, quotes or whitespace.
_USERNAME_RE = re.compile(r"^[a-z0-9._-]{1,64}$")


def normalize_username(raw: str) -> str:
    """Lower-case and strip a candidate username (normalisation only, no validation)."""
    return raw.strip().lower().replace(" ", "")


def split_person_name(value: str) -> tuple[str | None, str, str]:
    """Split a Zoho "Name" field summary value into (prefix, first, last).

    Zoho Forms renders a Name field into the ${zf:ALL_FIELDS} summary as its subfields in
    order, comma-separated — e.g. "Ms., Paula, Potgieter" (Prefix, First, Last) or
    "Paula, Potgieter" (First, Last) when no prefix is set. We only need first/last
    downstream; the prefix is returned for completeness.

    Untrusted input: this only splits/trims text — it never validates the username. The
    resulting first/last still flow through validate_username at the trust boundary.
    """
    parts = [p.strip() for p in value.split(",") if p.strip()]
    if len(parts) >= 3:
        return parts[0], parts[1], parts[-1]
    if len(parts) == 2:
        return None, parts[0], parts[1]
    if len(parts) == 1:
        # A single token (e.g. "Paula Potgieter" with a space, or just a first name).
        tokens = parts[0].split()
        if len(tokens) >= 2:
            return None, tokens[0], tokens[-1]
        return None, parts[0], ""
    return None, "", ""


def validate_username(name: str) -> str:
    """Return `name` if it satisfies the username policy, else raise InvalidTicketData.

    Policy: 1–64 chars of [a-z0-9._-], with at least one alphanumeric. This is an
    allow-list, so anything unexpected (quotes, '@', slashes, control chars, empty) is
    rejected — closing the gap where a crafted ticket username could target another
    account or be smuggled into a downstream query.
    """
    if not _USERNAME_RE.match(name) or not any(c.isalnum() for c in name):
        raise InvalidTicketData(f"username '{name}' is not within the allowed pattern")
    return name


class TicketType(str, Enum):
    STARTER = "starter"
    LEAVER = "leaver"


class StarterDetails(BaseModel):
    """The new-user fields we read from the ticket's user-info table.

    Field names are placeholders — map them to the real Zoho Desk custom-field API names
    in `lib/zoho.py:parse_ticket` once API access is available.
    """

    first_name: str
    last_name: str
    display_name: str | None = None
    job_title: str | None = None
    department: str | None = None
    role: str | None = Field(None, description="Drives role_group_map in client config")
    manager_email: str | None = None
    desired_username: str | None = None
    start_date: str | None = None

    @field_validator("first_name", "last_name")
    @classmethod
    def _require_non_empty(cls, value: str) -> str:
        """A starter with no name can't yield a safe username — reject early."""
        if not value or not value.strip():
            raise ValueError("must not be empty")
        return value.strip()


class Ticket(BaseModel):
    """A parsed, validated ticket ready for the orchestrator."""

    ticket_id: str
    client_id: str
    ticket_type: TicketType
    starter: StarterDetails | None = None
    # leaver details added in Phase E
