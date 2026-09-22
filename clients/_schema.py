"""Schema for per-client config files (`clients/<client-id>.yaml`).

A malformed client file should fail fast and loud rather than provisioning the wrong
thing. `lib/config.py` loads each YAML file and validates it against `ClientConfig`.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class IdentityPath(str, Enum):
    """Which identity platform a client provisions into."""

    ENTRA = "entra"          # Azure-only: Microsoft Graph creates the cloud user
    LOCAL_AD = "local_ad"    # On-prem AD via Hybrid Runbook Worker, synced up by AD Connect


class ClientConfig(BaseModel):
    """Validated shape of one client's process definition."""

    client_id: str = Field(..., description="Stable id; matches the file name and Zoho Desk mapping")
    identity_path: IdentityPath

    # Entra path
    tenant_id: str | None = Field(None, description="Entra tenant GUID (required for entra path)")

    # Local-AD path (Azure Automation runbook on a Hybrid Worker)
    automation_account: str | None = Field(
        None, description="Azure Automation account name (required for local_ad path)"
    )
    hybrid_worker_group: str | None = Field(
        None, description="Hybrid Worker group to run the runbook on (local_ad path)"
    )
    subscription_id: str | None = Field(None, description="Azure subscription id (local_ad path)")
    resource_group: str | None = Field(
        None, description="Resource group holding the Automation account (local_ad path)"
    )
    runbook_name: str = Field("Create-AdUser", description="Runbook to start for new users")
    ou_path: str | None = Field(None, description="AD OU distinguished name for new users")

    # Provisioning
    license_skus: list[str] = Field(default_factory=list, description="Graph SKU ids/part numbers")
    default_groups: list[str] = Field(default_factory=list)
    role_group_map: dict[str, list[str]] = Field(
        default_factory=dict, description="Map ticket 'role' value -> extra groups"
    )
    usage_location: str | None = Field(None, description="Two-letter country code, e.g. GB")
    upn_suffix: str | None = Field(
        None, description="UPN/email domain, e.g. acme.com. If unset, the tenant default is used"
    )
    username_format: str = Field(
        "{first}.{last}",
        description="Username template. Tokens: {first} {last} {first_initial} {last_initial}",
    )

    # Safety
    approval_required: bool = True

    def validate_for_path(self) -> None:
        """Cross-field checks the type system can't express on its own."""
        if self.identity_path is IdentityPath.ENTRA and not self.tenant_id:
            raise ValueError(f"client '{self.client_id}': entra path requires tenant_id")
        if self.identity_path is IdentityPath.LOCAL_AD and not (
            self.automation_account
            and self.hybrid_worker_group
            and self.subscription_id
            and self.resource_group
        ):
            raise ValueError(
                f"client '{self.client_id}': local_ad path requires automation_account, "
                "hybrid_worker_group, subscription_id and resource_group"
            )
