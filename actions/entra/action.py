"""Entra (Azure-only) provisioning via Microsoft Graph (Phase B).

Implements the fixed, validated operations of the constrained action layer using Graph
REST. The transport is injectable so unit tests run with a fake and never hit the network.
Live calls require a real per-client app registration (see lib.graph / lib.secrets).
"""

from __future__ import annotations

import secrets
import string

import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent))

from actions.base import (  # noqa: E402
    ProvisioningAction,
    ProvisioningPlan,
    UserCollisionError,
)
from lib.graph import GraphTransport, RealGraphTransport  # noqa: E402


def _temp_password(length: int = 16) -> str:
    """Generate a random temp password (user must change at first logon)."""
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    return "".join(secrets.choice(alphabet) for _ in range(length))


class EntraAction(ProvisioningAction):
    def __init__(self, tenant_id: str, transport: GraphTransport | None = None) -> None:
        self.tenant_id = tenant_id
        # Build the live transport lazily only if one wasn't injected (tests inject a fake).
        self._transport = transport
        self._sku_cache: dict[str, str] | None = None

    @property
    def graph(self) -> GraphTransport:
        if self._transport is None:
            self._transport = RealGraphTransport(self.tenant_id)
        return self._transport

    # --------------------------------------------------------------- create
    def create_user(self, plan: ProvisioningPlan) -> str:
        suffix = plan.upn_suffix or self._verified_domain()
        upn = f"{plan.username}@{suffix}"

        # Reuse the existing object ONLY when the orchestrator confirms we created it on a
        # previous attempt of this ticket (safe re-run). Otherwise an account already
        # holding this UPN is an unexpected collision — refuse rather than mutate it.
        existing = self._find_user_id(upn)
        if existing:
            if not plan.allow_existing_user:
                raise UserCollisionError(
                    f"user '{upn}' already exists and was not created by this ticket; "
                    "refusing to assign licenses/groups to it"
                )
            return existing

        body = {
            "accountEnabled": True,
            "displayName": plan.display_name,
            "mailNickname": plan.username,
            "userPrincipalName": upn,
            "usageLocation": plan.usage_location,
            "passwordProfile": {
                "forceChangePasswordNextSignIn": True,
                "password": _temp_password(),
            },
        }
        created = self.graph.post("/users", json=body)
        assert created is not None
        return created["id"]

    def _find_user_id(self, upn: str) -> str | None:
        escaped = upn.replace("'", "''")
        data = self.graph.get("/users", params={"$filter": f"userPrincipalName eq '{escaped}'"})
        values = data.get("value", [])
        return values[0]["id"] if values else None

    def _verified_domain(self) -> str:
        """Pick the tenant's primary verified domain for the UPN suffix."""
        data = self.graph.get("/domains")
        domains = data.get("value", [])
        for d in domains:
            if d.get("isDefault"):
                return d["id"]
        # Fall back to first verified domain.
        return domains[0]["id"] if domains else "onmicrosoft.com"

    # -------------------------------------------------------------- license
    def assign_license(self, plan: ProvisioningPlan, user_id: str) -> None:
        sku_ids = self._resolve_sku_ids(plan.license_skus)
        # Idempotent: skip SKUs already assigned to this user.
        already = self._current_license_skus(user_id)
        to_add = [sid for sid in sku_ids if sid not in already]
        if not to_add:
            return
        body = {"addLicenses": [{"skuId": sid, "disabledPlans": []} for sid in to_add],
                "removeLicenses": []}
        self.graph.post(f"/users/{user_id}/assignLicense", json=body)

    def _current_license_skus(self, user_id: str) -> set[str]:
        data = self.graph.get(f"/users/{user_id}/licenseDetails")
        return {item["skuId"] for item in data.get("value", [])}

    def _resolve_sku_ids(self, sku_part_numbers: list[str]) -> list[str]:
        """Map human SKU part numbers (e.g. O365_BUSINESS_PREMIUM) to skuId GUIDs."""
        if self._sku_cache is None:
            data = self.graph.get("/subscribedSkus")
            self._sku_cache = {
                s["skuPartNumber"]: s["skuId"] for s in data.get("value", [])
            }
        resolved = []
        for part in sku_part_numbers:
            sku_id = self._sku_cache.get(part)
            if sku_id is None:
                raise ValueError(f"License SKU '{part}' not found in tenant subscribedSkus")
            resolved.append(sku_id)
        return resolved

    # --------------------------------------------------------------- groups
    def add_groups(self, plan: ProvisioningPlan, user_id: str) -> None:
        # Idempotent: fetch current memberships once and skip groups already joined.
        current = self._current_group_ids(user_id)
        for name in plan.groups:
            group_id = self._resolve_group_id(name)
            if group_id in current:
                continue
            self.graph.post(
                f"/groups/{group_id}/members/$ref",
                json={"@odata.id": f"https://graph.microsoft.com/v1.0/directoryObjects/{user_id}"},
            )

    def _current_group_ids(self, user_id: str) -> set[str]:
        data = self.graph.get(f"/users/{user_id}/memberOf")
        return {obj["id"] for obj in data.get("value", []) if "id" in obj}

    def _resolve_group_id(self, display_name: str) -> str:
        escaped = display_name.replace("'", "''")
        data = self.graph.get("/groups", params={"$filter": f"displayName eq '{escaped}'"})
        values = data.get("value", [])
        if not values:
            raise ValueError(f"Group '{display_name}' not found in tenant")
        return values[0]["id"]
