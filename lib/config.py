"""Load and validate per-client config files from `clients/`.

Files are version-controlled YAML, one per client, validated against
`clients/_schema.ClientConfig`. A malformed file raises rather than guessing.
"""

from __future__ import annotations

import importlib.util
import logging
import os
import pathlib
import re
import sys
import time
from typing import Callable

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
    """The ticket's client couldn't be matched to any config file."""


class AmbiguousClientError(UnknownClientError):
    """The ticket's clues point at more than one client — never guess between them."""


# A config file stem: lower-case letters, digits, '-' and '_'. Anything else (e.g. text typed
# on a form such as "../x") is never turned into a file path.
_SAFE_STEM = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


def _is_client_stem(value: str) -> bool:
    return bool(_SAFE_STEM.match(value)) and (CLIENTS_DIR / f"{value}.yaml").is_file()


def load_lookup() -> dict[str, str]:
    """Zoho Desk client id -> config file stem. See clients/_lookup.yaml."""
    if not LOOKUP_PATH.exists():
        return {}
    data = yaml.safe_load(LOOKUP_PATH.read_text(encoding="utf-8")) or {}
    # Normalise keys to str so numeric Desk ids match whether quoted or not.
    return {str(k): str(v) for k, v in data.items()}


def _lookup_company(company: str) -> str | None:
    """Company-name alias -> config stem via clients/_lookup.yaml (case-insensitive)."""
    lookup = load_lookup()
    stem = lookup.get(company)
    if stem is None:
        # Company names typed on a form vary in case/whitespace — match case-insensitively.
        ci = {k.strip().lower(): v for k, v in lookup.items()}
        stem = ci.get(company.strip().lower())
    return stem


def resolve_config(client_key: str) -> ClientConfig:
    """Map a client key to its validated config.

    The key is either a company-name alias from clients/_lookup.yaml or a config file stem
    (what identify_client returns). Raises UnknownClientError otherwise — the caller should
    flag the ticket for a human rather than guess.
    """
    key = str(client_key)
    stem = _lookup_company(key)
    if stem is None and _is_client_stem(key):
        stem = key
    if stem is None:
        raise UnknownClientError(f"client '{client_key}' has no config in clients/")
    return load_client(stem)


def load_client(client_id: str) -> ClientConfig:
    """Load and validate a single client's config.

    Raises FileNotFoundError if the client is unknown, ValueError if the file is invalid.
    """
    if not _SAFE_STEM.match(client_id):
        raise FileNotFoundError(f"Invalid client id '{client_id}'")
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


# --------------------------------------------------------------------------- identification
#
# Onboarding forms differ per client and all arrive at the same helpdesk mailbox, so the
# ticket doesn't say which client it's for. We combine clues — the "Company's Name" answer
# (when the form has one) and every email domain in the summary — and accept the result only
# when they point at exactly one client.
#
# Domains are discovered from each client's Microsoft tenant (its verified domains), so a
# client with several domains needs no list maintained here, and a new domain is picked up
# on the next refresh. `email_domains:` in a client file is only an optional extra.

DomainFetcher = Callable[[ClientConfig], list[str]]

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+'-]+@([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+)")


def graph_verified_domains(config: ClientConfig) -> list[str]:
    """The client tenant's verified domains, via Microsoft Graph GET /domains.

    Needs the Domain.Read.All application permission in the client tenant.
    """
    tenant = config.tenant_id or ""
    if not tenant or tenant.startswith("PLACEHOLDER"):
        return []
    from .graph import RealGraphTransport  # lazy: keeps config import free of network deps

    data = RealGraphTransport(tenant).get("/domains")
    return [
        str(d["id"]).lower()
        for d in data.get("value", [])
        if d.get("isVerified") and d.get("id")
    ]


_domain_fetcher: DomainFetcher = graph_verified_domains
_index_cache: tuple[float, dict[str, set[str]]] | None = None


def _index_ttl() -> float:
    try:
        return float(os.environ.get("DOMAIN_INDEX_TTL_SECONDS", 6 * 3600))
    except ValueError:
        return 6 * 3600.0


def set_domain_fetcher(fetcher: DomainFetcher) -> None:
    """Swap how a client's domains are found (tests / dev) and drop the cached index."""
    global _domain_fetcher, _index_cache
    _domain_fetcher = fetcher
    _index_cache = None


def _client_stems() -> list[str]:
    return sorted(
        p.stem for p in CLIENTS_DIR.glob("*.yaml") if not p.stem.startswith("_")
    )


def build_domain_index(fetcher: DomainFetcher | None = None) -> dict[str, set[str]]:
    """domain -> set of client stems. A client that can't be loaded or reached is skipped.

    A domain claimed by more than one client keeps all of them, so any ticket relying on it
    resolves as ambiguous (flagged) rather than routed to the wrong client.
    """
    fetch = fetcher or _domain_fetcher
    index: dict[str, set[str]] = {}
    for stem in _client_stems():
        try:
            config = load_client(stem)
        except Exception as exc:  # noqa: BLE001 - one bad file mustn't block every client
            logging.warning("Skipping client '%s' in domain index: %s", stem, exc)
            continue
        domains = set(config.email_domains)
        try:
            domains.update(d.lower() for d in fetch(config))
        except Exception as exc:  # noqa: BLE001 - one unreachable tenant mustn't block others
            logging.warning("Couldn't read domains for client '%s': %s", stem, exc)
        for domain in domains:
            index.setdefault(domain, set()).add(stem)
    for domain, stems in index.items():
        if len(stems) > 1:
            logging.warning("Domain '%s' belongs to several clients %s", domain, sorted(stems))
    return index


def domain_index() -> dict[str, set[str]]:
    """Cached domain index, rebuilt after DOMAIN_INDEX_TTL_SECONDS (default 6h)."""
    global _index_cache
    now = time.monotonic()
    if _index_cache is None or now - _index_cache[0] > _index_ttl():
        _index_cache = (now, build_domain_index())
    return _index_cache[1]


def email_domains_in(text: str) -> list[str]:
    """Distinct email domains appearing anywhere in the text, lower-cased, in order."""
    seen: list[str] = []
    for m in _EMAIL_RE.finditer(text or ""):
        domain = m.group(1).lower().rstrip(".")
        if domain not in seen:
            seen.append(domain)
    return seen


def identify_client(
    company: str | None,
    body: str,
    index: dict[str, set[str]] | None = None,
) -> str:
    """Work out the client's config stem from the ticket's clues.

    Exactly one client -> its stem. No match -> UnknownClientError. Clues pointing at
    different clients -> AmbiguousClientError. Domains that belong to no client (e.g. the
    MSP's own helpdesk address in the email text) are ignored.
    """
    candidates: set[str] = set()
    if company:
        stem = _lookup_company(company)
        if stem and _is_client_stem(stem):
            candidates.add(stem)
    idx = domain_index() if index is None else index
    for domain in email_domains_in(body):
        candidates |= idx.get(domain, set())

    if len(candidates) == 1:
        return next(iter(candidates))
    if not candidates:
        raise UnknownClientError("no company name or email domain matched a client")
    raise AmbiguousClientError(f"clues match several clients: {', '.join(sorted(candidates))}")
