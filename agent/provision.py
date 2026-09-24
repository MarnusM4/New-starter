"""Approval gate + provisioning dispatcher (Phase B).

The orchestrator builds a ProvisioningPlan, then:
  1. If approval is required and the ticket isn't approved yet -> post the plan and stop.
  2. Once approved (or approval not required) -> dispatch to the matching action.

The dispatcher is the ONLY place that triggers privileged writes. It routes by
identity_path, runs the fixed operations, posts results back to the Zoho Desk ticket, and
audits each step.
"""

from __future__ import annotations

import sys
import pathlib
from typing import Any

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from actions.base import ProvisioningPlan  # noqa: E402
from actions.entra.action import EntraAction  # noqa: E402
from actions.local_ad.action import LocalAdAction  # noqa: E402
from lib.audit import audit  # noqa: E402
from lib.config import ClientConfig, IdentityPath  # noqa: E402

# Placeholder approval signal. TODO: confirm how approval is represented in Zoho Desk
# (a named status, a custom checkbox/picklist field under `cf`, or a Blueprint transition).
# The Desk webhook/workflow must be configured to also fire on the ticket UPDATE that sets
# this so the approval re-enters the orchestrator.
APPROVED_STATUS = "approved"


def _cf(raw: dict[str, Any]) -> dict[str, Any]:
    """Zoho Desk custom fields live under the `cf` object; tolerate its absence."""
    return raw.get("cf", {}) or {}


def is_approved(raw: dict[str, Any]) -> bool:
    """Has a technician approved this ticket for provisioning?"""
    status = str(raw.get("status", "")).lower()
    if status == APPROVED_STATUS:
        return True
    # TODO: real Desk custom-field API name for the approval flag.
    return bool(_cf(raw).get("cf_provisioning_approved") or raw.get("provisioning_approved", False))


def approver(raw: dict[str, Any]) -> str:
    """Who approved (for the audit trail). TODO: real Desk field for the approving agent."""
    return str(
        _cf(raw).get("cf_approved_by")
        or raw.get("approved_by")
        or raw.get("assigneeId")
        or "unknown"
    )


def requester(raw: dict[str, Any]) -> str:
    """Who raised the request. TODO: confirm the real Desk field(s).

    Desk exposes the requester under `contact` (e.g. contact.email); fall back to the
    generic keys used elsewhere/in tests.
    """
    contact = raw.get("contact", {}) or {}
    return str(
        contact.get("email")
        or raw.get("reported_by")
        or raw.get("requester")
        or raw.get("email")
        or ""
    )


def self_approved(raw: dict[str, Any]) -> bool:
    """True when the approver is the same identity as the requester.

    Separation of duties: the person who requested an account must not be the one who
    approves its creation. We can only enforce this when both identities are present; if
    either is unknown we don't *assert* a violation here (the approval still has to pass
    `is_approved`, which fails closed).
    """
    appr = approver(raw).strip().lower()
    req = requester(raw).strip().lower()
    return bool(req) and appr not in ("", "unknown") and appr == req


def _build_action(config: ClientConfig):
    if config.identity_path is IdentityPath.ENTRA:
        assert config.tenant_id
        return EntraAction(tenant_id=config.tenant_id)
    assert config.tenant_id  # tenant still needed for the ARM token on local_ad
    return LocalAdAction(
        tenant_id=config.tenant_id or "",
        subscription_id=config.subscription_id or "",
        resource_group=config.resource_group or "",
        automation_account=config.automation_account or "",
        hybrid_worker_group=config.hybrid_worker_group or "",
        runbook_name=config.runbook_name,
        ou_path=config.ou_path,
    )


def provision(
    plan: ProvisioningPlan,
    config: ClientConfig,
    action=None,
    *,
    on_user_created=None,
) -> dict[str, Any]:
    """Execute the plan via the matching action. Returns a result summary.

    `action` is injectable for tests; production builds it from config.
    `on_user_created` is an optional callback fired the moment the user object exists, so
    the caller can durably record that fact (enabling safe, idempotent reuse on retry
    even if a later step fails).
    """
    action = action or _build_action(config)
    result: dict[str, Any] = {"ticket_id": plan.ticket_id, "steps": []}

    audit("provision.start", plan.ticket_id, identity_path=plan.identity_path)

    user_id = action.create_user(plan)
    if on_user_created is not None:
        on_user_created()
    result["user_id"] = user_id
    result["steps"].append("create_user")
    audit("provision.user_created", plan.ticket_id, user_id=user_id)

    if config.identity_path is IdentityPath.ENTRA:
        action.assign_license(plan, user_id)
        result["steps"].append("assign_license")
        audit("provision.license_assigned", plan.ticket_id, skus=plan.license_skus)

        action.add_groups(plan, user_id)
        result["steps"].append("add_groups")
        audit("provision.groups_added", plan.ticket_id, groups=plan.groups)
    else:
        # local_ad: the runbook created the AD user + on-prem groups. Cloud licensing /
        # cloud-only groups depend on AD Connect sync completing first.
        result["steps"].append("ad_user_created_pending_sync")
        audit("provision.local_ad_pending_sync", plan.ticket_id)

    audit("provision.done", plan.ticket_id, steps=result["steps"])
    return result


def result_note(result: dict[str, Any]) -> str:
    lines = ["**Provisioning complete**", f"- User: {result.get('user_id', '(see logs)')}",
             f"- Steps: {', '.join(result['steps'])}"]
    if "ad_user_created_pending_sync" in result["steps"]:
        lines.append("- Note: licensing/cloud groups apply after AD Connect sync.")
    return "\n".join(lines)
