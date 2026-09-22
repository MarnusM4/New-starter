"""Secret resolution.

Phase B: reads from environment / Function app settings. In production point this at
Azure Key Vault (azure-keyvault-secrets) so per-client app secrets never touch the repo
or env files. Keeping the lookup behind one function makes that swap a one-place change.
"""

from __future__ import annotations

import os


class MissingSecret(RuntimeError):
    pass


def get_secret(name: str, *, required: bool = True) -> str:
    """Resolve a secret by name: environment first, then Azure Key Vault.

    Env wins (handy for local dev / Function app settings). If unset and KEY_VAULT_URL is
    configured, look the secret up in Key Vault. Placeholder values are treated as unset.
    """
    value = os.environ.get(name, "")
    if value and not value.startswith("PLACEHOLDER"):
        return value

    vault_value = _from_key_vault(name)
    if vault_value:
        return vault_value

    if required:
        raise MissingSecret(
            f"Secret '{name}' is not set (or still a placeholder). "
            "Set it in Function app settings / Key Vault before provisioning."
        )
    return ""


def _from_key_vault(name: str) -> str | None:
    """Look a secret up in Azure Key Vault if KEY_VAULT_URL is configured.

    Imports are deferred so the app runs without azure-keyvault-secrets installed.
    Key Vault secret names can't contain '_', so AZURE_CLIENT_ID -> azure-client-id.
    NOTE: not yet exercised against a live vault — see ROADMAP "Deferred / hardening".
    """
    vault_url = os.environ.get("KEY_VAULT_URL", "")
    if not vault_url:
        return None
    try:
        from azure.identity import DefaultAzureCredential
        from azure.keyvault.secrets import SecretClient
    except ImportError:
        return None
    client = SecretClient(vault_url=vault_url, credential=DefaultAzureCredential())
    return client.get_secret(name.replace("_", "-")).value
