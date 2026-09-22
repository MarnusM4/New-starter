"""Common interface for the constrained action layer.

The agent/orchestrator NEVER calls Graph or AD directly. It builds a ProvisioningPlan
(structured, validated) and hands it to a ProvisioningAction implementation, which holds
the privileged credentials and performs only these fixed operations.
"""

from __future__ import annotations

import abc

from pydantic import BaseModel

import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from lib.ticket import Ticket  # noqa: E402

# Imported lazily to avoid circulars; ClientConfig comes from lib.config at call time.


class UserCollisionError(Exception):
    """An account matching the planned identity already exists, unexpectedly.

    Creation is idempotent for *safe re-runs* (we created the user on a previous attempt
    of the SAME ticket). But finding a pre-existing account we did not create is treated
    as a collision and refused — otherwise a crafted ticket username could redirect
    licensing/group changes onto someone else's (possibly privileged) account.
    """


class ProvisioningPlan(BaseModel):
    """What we INTEND to do — produced in Phase A, executed in Phase B."""

    client_id: str
    ticket_id: str
    identity_path: str
    username: str
    display_name: str
    license_skus: list[str]
    groups: list[str]
    usage_location: str | None = None
    upn_suffix: str | None = None
    # Set True by the orchestrator ONLY when durable state shows we already created this
    # ticket's user on a prior attempt, so reusing the existing object is the safe,
    # idempotent thing to do. Defaults False: an unexpected existing user is a collision.
    allow_existing_user: bool = False

    def to_note(self) -> str:
        """Human-readable summary for the HALO ticket note / approval gate."""
        lines = [
            "**Proposed provisioning plan**",
            f"- Client: {self.client_id}",
            f"- Identity path: {self.identity_path}",
            f"- Username: {self.username}",
            f"- Display name: {self.display_name}",
            f"- Licenses: {', '.join(self.license_skus) or '(none)'}",
            f"- Groups: {', '.join(self.groups) or '(none)'}",
            f"- Usage location: {self.usage_location or '(unset)'}",
            "",
            "_No changes have been made. Awaiting approval (Phase B)._",
        ]
        return "\n".join(lines)


class ProvisioningAction(abc.ABC):
    """Fixed set of privileged operations. Implementations: entra, local_ad."""

    @abc.abstractmethod
    def create_user(self, plan: ProvisioningPlan) -> str:
        """Create the account; return the created user id/UPN. (Phase B)"""

    @abc.abstractmethod
    def assign_license(self, plan: ProvisioningPlan, user_id: str) -> None:
        """Assign licenses from the plan. (Phase B)"""

    @abc.abstractmethod
    def add_groups(self, plan: ProvisioningPlan, user_id: str) -> None:
        """Add the user to the planned groups. (Phase B)"""
