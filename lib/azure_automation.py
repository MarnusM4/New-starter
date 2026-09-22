"""Azure Automation REST transport (local-AD path).

Starts a PowerShell runbook job on a Hybrid Runbook Worker group and polls it to
completion. Uses ARM REST with client-credentials auth (scope management.azure.com).
Injectable so LocalAdAction is unit-testable without hitting Azure.
"""

from __future__ import annotations

import uuid
from typing import Any, Protocol

import requests

from .retry import with_retries
from .secrets import get_secret

ARM_BASE = "https://management.azure.com"
API_VERSION = "2023-11-01"
TERMINAL_STATES = {"Completed", "Failed", "Stopped", "Suspended"}


class AutomationTransport(Protocol):
    def start_job(self, runbook: str, parameters: dict[str, Any], run_on: str) -> str: ...
    def get_job_status(self, job_name: str) -> str: ...


class RealAutomationTransport:
    def __init__(self, subscription_id: str, resource_group: str, automation_account: str,
                 tenant_id: str) -> None:
        self.subscription_id = subscription_id
        self.resource_group = resource_group
        self.automation_account = automation_account
        self.tenant_id = tenant_id
        self._token: str | None = None

    def _get_token(self) -> str:
        if self._token:
            return self._token
        client_id = get_secret("AZURE_CLIENT_ID")
        client_secret = get_secret("AZURE_CLIENT_SECRET")
        resp = requests.post(
            f"https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0/token",
            data={
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
                "scope": "https://management.azure.com/.default",
            },
            timeout=30,
        )
        resp.raise_for_status()
        self._token = resp.json()["access_token"]
        return self._token

    def _job_url(self, job_name: str) -> str:
        return (
            f"{ARM_BASE}/subscriptions/{self.subscription_id}/resourceGroups/{self.resource_group}"
            f"/providers/Microsoft.Automation/automationAccounts/{self.automation_account}"
            f"/jobs/{job_name}?api-version={API_VERSION}"
        )

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._get_token()}", "Content-Type": "application/json"}

    def start_job(self, runbook: str, parameters: dict[str, Any], run_on: str) -> str:
        job_name = str(uuid.uuid4())
        body = {
            "properties": {
                "runbook": {"name": runbook},
                "parameters": {k: str(v) for k, v in parameters.items()},
                "runOn": run_on,  # Hybrid Worker group name
            }
        }
        def call() -> None:
            resp = requests.put(
                self._job_url(job_name), headers=self._headers(), json=body, timeout=30
            )
            resp.raise_for_status()

        with_retries(call)
        return job_name

    def get_job_status(self, job_name: str) -> str:
        def call() -> str:
            resp = requests.get(self._job_url(job_name), headers=self._headers(), timeout=30)
            resp.raise_for_status()
            return resp.json()["properties"]["status"]

        return with_retries(call)
