"""Local-AD provisioning via an Azure Automation Hybrid Runbook Worker (Phase B).

Microsoft Graph CANNOT write on-prem AD. This action starts a PowerShell runbook
(runbook.ps1) on the client's Hybrid Worker, which runs `New-ADUser` locally with
line-of-sight to the domain controller. Azure AD Connect then syncs the user up to Entra,
after which licensing/cloud-group steps run via the Entra path (in the dispatcher).

The transport is injectable so this is unit-testable without hitting Azure.
"""

from __future__ import annotations

import time

import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent))

from actions.base import ProvisioningAction, ProvisioningPlan  # noqa: E402
from lib.azure_automation import (  # noqa: E402
    TERMINAL_STATES,
    AutomationTransport,
    RealAutomationTransport,
)


class LocalAdAction(ProvisioningAction):
    def __init__(
        self,
        *,
        tenant_id: str,
        subscription_id: str,
        resource_group: str,
        automation_account: str,
        hybrid_worker_group: str,
        runbook_name: str,
        ou_path: str | None,
        transport: AutomationTransport | None = None,
        poll_interval: float = 5.0,
        timeout: float = 600.0,
    ) -> None:
        self.hybrid_worker_group = hybrid_worker_group
        self.runbook_name = runbook_name
        self.ou_path = ou_path
        self.poll_interval = poll_interval
        self.timeout = timeout
        self._transport = transport
        self._ctx = dict(
            tenant_id=tenant_id,
            subscription_id=subscription_id,
            resource_group=resource_group,
            automation_account=automation_account,
        )

    @property
    def automation(self) -> AutomationTransport:
        if self._transport is None:
            self._transport = RealAutomationTransport(
                subscription_id=self._ctx["subscription_id"],
                resource_group=self._ctx["resource_group"],
                automation_account=self._ctx["automation_account"],
                tenant_id=self._ctx["tenant_id"],
            )
        return self._transport

    def create_user(self, plan: ProvisioningPlan) -> str:
        first, _, last = plan.display_name.partition(" ")
        params = {
            "FirstName": first,
            "LastName": last,
            "SamAccountName": plan.username,
            # Use the client's configured UPN/email domain; client_id is only a last-resort
            # fallback (it is not a routable domain — see config.upn_suffix).
            "UserPrincipalName": f"{plan.username}@{plan.upn_suffix or plan.client_id}",
            "DisplayName": plan.display_name,
            "OUPath": self.ou_path or "",
            "Groups": ",".join(plan.groups),
        }
        job_name = self.automation.start_job(
            runbook=self.runbook_name, parameters=params, run_on=self.hybrid_worker_group
        )
        self._wait_for_job(job_name)
        return plan.username  # samAccountName; Entra object id resolved post-sync (Phase B+)

    def _wait_for_job(self, job_name: str) -> None:
        deadline = time.monotonic() + self.timeout
        while True:
            status = self.automation.get_job_status(job_name)
            if status in TERMINAL_STATES:
                if status != "Completed":
                    raise RuntimeError(f"Runbook job {job_name} ended in state '{status}'")
                return
            if time.monotonic() > deadline:
                raise TimeoutError(f"Runbook job {job_name} did not finish within {self.timeout}s")
            time.sleep(self.poll_interval)

    def assign_license(self, plan: ProvisioningPlan, user_id: str) -> None:
        # Licensing happens in Entra AFTER AD Connect sync; the dispatcher handles this
        # by invoking the Entra path once the synced object exists.
        raise NotImplementedError("local_ad licensing is applied via the Entra path post-sync")

    def add_groups(self, plan: ProvisioningPlan, user_id: str) -> None:
        # On-prem groups are set inside the runbook (Groups param). Cloud-only groups, if any,
        # are applied via the Entra path post-sync by the dispatcher.
        raise NotImplementedError("local_ad on-prem groups are set in the runbook")
