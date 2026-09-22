"""Microsoft Graph HTTP transport (Entra path).

Thin synchronous wrapper over Graph REST using client-credentials auth. We use REST
directly (not the async msgraph-sdk) to keep the orchestrator synchronous and the calls
easy to read and unit-test. EntraAction depends on the GraphTransport protocol, so tests
inject a fake and never hit the network.

Credentials: per-client app registration. tenant_id comes from client config;
AZURE_CLIENT_ID / AZURE_CLIENT_SECRET come from Key Vault / app settings (see lib.secrets).
"""

from __future__ import annotations

from typing import Any, Protocol

import requests

from .retry import with_retries
from .secrets import get_secret

GRAPH_BASE = "https://graph.microsoft.com/v1.0"


class GraphTransport(Protocol):
    def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]: ...
    def post(self, path: str, json: dict[str, Any] | None = None) -> dict[str, Any] | None: ...


class RealGraphTransport:
    """Live Graph transport. Acquires a token lazily; refuses placeholder creds."""

    def __init__(self, tenant_id: str) -> None:
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
                "scope": "https://graph.microsoft.com/.default",
            },
            timeout=30,
        )
        resp.raise_for_status()
        self._token = resp.json()["access_token"]
        return self._token

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._get_token()}",
            "Content-Type": "application/json",
        }

    def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        def call() -> dict[str, Any]:
            resp = requests.get(
                f"{GRAPH_BASE}{path}", headers=self._headers(), params=params, timeout=30
            )
            resp.raise_for_status()
            return resp.json()

        return with_retries(call)

    def post(self, path: str, json: dict[str, Any] | None = None) -> dict[str, Any] | None:
        def call() -> dict[str, Any] | None:
            resp = requests.post(
                f"{GRAPH_BASE}{path}", headers=self._headers(), json=json, timeout=30
            )
            resp.raise_for_status()
            if resp.status_code == 204 or not resp.content:
                return None
            return resp.json()

        return with_retries(call)
