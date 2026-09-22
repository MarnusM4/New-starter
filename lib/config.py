"""Load and validate per-client config files from `clients/`.

Files are version-controlled YAML, one per client, validated against
`clients/_schema.ClientConfig`. A malformed file raises rather than guessing.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

import yaml

# Load the schema module by path (the `clients` dir isn't a package).
_SCHEMA_PATH = pathlib.Path(__file__).resolve().parent.parent / "clients" / "_schema.py"
_spec = importlib.util.spec_from_file_location("clients_schema", _SCHEMA_PATH)
assert _spec and _spec.loader
_schema = importlib.util.module_from_spec(_spec)
# Register before exec so pydantic can resolve forward-referenced annotations
# (e.g. IdentityPath) via sys.modules[cls.__module__].
sys.modules["clients_schema"] = _schema
_spec.loader.exec_module(_schema)

ClientConfig = _schema.ClientConfig
IdentityPath = _schema.IdentityPath

CLIENTS_DIR = pathlib.Path(__file__).resolve().parent.parent / "clients"
LOOKUP_PATH = CLIENTS_DIR / "_lookup.yaml"


class UnknownClientError(Exception):
    """The Zoho Desk client on the ticket isn't mapped to any config file."""


def load_lookup() -> dict[str, str]:
    """Zoho Desk client id -> config file stem. See clients/_lookup.yaml."""
    if not LOOKUP_PATH.exists():
        return {}
    data = yaml.safe_load(LOOKUP_PATH.read_text(encoding="utf-8")) or {}
    # Normalise keys to str so numeric Desk ids match whether quoted or not.
    return {str(k): str(v) for k, v in data.items()}


def resolve_config(desk_client_id: str) -> ClientConfig:
    """Map a Zoho Desk client id to its validated config, via the lookup table.

    Raises UnknownClientError if the client isn't mapped — the caller should flag the
    ticket for a human rather than guess.
    """
    lookup = load_lookup()
    stem = lookup.get(str(desk_client_id))
    if stem is None:
        raise UnknownClientError(
            f"Zoho Desk client '{desk_client_id}' is not mapped in clients/_lookup.yaml"
        )
    return load_client(stem)


def load_client(client_id: str) -> ClientConfig:
    """Load and validate a single client's config.

    Raises FileNotFoundError if the client is unknown, ValueError if the file is invalid.
    """
    path = CLIENTS_DIR / f"{client_id}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"No config for client '{client_id}' (expected {path})")

    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    config = ClientConfig(**data)
    config.validate_for_path()
    return config


def load_all_clients() -> dict[str, ClientConfig]:
    """Load every client config (skips files starting with '_', e.g. _schema)."""
    out: dict[str, ClientConfig] = {}
    for path in CLIENTS_DIR.glob("*.yaml"):
        if path.stem.startswith("_"):
            continue
        config = load_client(path.stem)
        out[config.client_id] = config
    return out
