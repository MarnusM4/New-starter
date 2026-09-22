"""Durable processing state (idempotency).

The webhook front door and the reconciliation poll are SEPARATE Azure Function
invocations — in-memory sets can't dedupe across them, and don't survive restarts. So
idempotency lives behind a small StateStore interface:

  - FileState     : JSON file, fine for local dev / single instance.
  - InMemoryState : tests.
  - (prod)        : back this with Azure Table Storage / Cosmos so it's shared and durable.

Keys are namespaced strings, e.g. "provisioned:T-1001".
"""

from __future__ import annotations

import json
import os
import pathlib
import threading
from typing import Protocol


class StateStore(Protocol):
    def is_done(self, key: str) -> bool: ...
    def mark_done(self, key: str) -> None: ...
    def claim(self, key: str) -> bool: ...
    def release(self, key: str) -> None: ...


class InMemoryState:
    def __init__(self) -> None:
        self._keys: set[str] = set()

    def is_done(self, key: str) -> bool:
        return key in self._keys

    def mark_done(self, key: str) -> None:
        self._keys.add(key)

    def claim(self, key: str) -> bool:
        if key in self._keys:
            return False
        self._keys.add(key)
        return True

    def release(self, key: str) -> None:
        self._keys.discard(key)


class FileState:
    """JSON-file-backed store. Not safe across concurrent instances — use Azure Table
    in production. Adequate for local dev and a single Function instance."""

    def __init__(self, path: str = "./state.json") -> None:
        self._path = pathlib.Path(path)
        self._lock = threading.Lock()

    def _load(self) -> set[str]:
        if not self._path.exists():
            return set()
        return set(json.loads(self._path.read_text(encoding="utf-8")))

    def is_done(self, key: str) -> bool:
        with self._lock:
            return key in self._load()

    def mark_done(self, key: str) -> None:
        with self._lock:
            keys = self._load()
            keys.add(key)
            self._path.write_text(json.dumps(sorted(keys)), encoding="utf-8")

    def claim(self, key: str) -> bool:
        # Atomic under the in-process lock (single-instance dev only — prod uses
        # AzureTableState, which is atomic across instances).
        with self._lock:
            keys = self._load()
            if key in keys:
                return False
            keys.add(key)
            self._path.write_text(json.dumps(sorted(keys)), encoding="utf-8")
            return True

    def release(self, key: str) -> None:
        with self._lock:
            keys = self._load()
            if key in keys:
                keys.discard(key)
                self._path.write_text(json.dumps(sorted(keys)), encoding="utf-8")


class AzureTableState:
    """Production state store backed by Azure Table Storage.

    Shared across Function instances and durable across restarts — the correct choice for
    prod (FileState is dev-only). Requires `azure-data-tables`; the import is deferred so
    the rest of the app runs without it installed.

    NOTE: not yet exercised against a live account — see ROADMAP "Deferred / hardening".
    Wire via env: STATE_TABLE_CONNECTION_STRING + STATE_TABLE_NAME (default "agentstate").
    """

    def __init__(self, connection_string: str, table_name: str = "agentstate") -> None:
        from azure.data.tables import TableClient  # deferred import

        self._client = TableClient.from_connection_string(connection_string, table_name)
        try:
            self._client.create_table()
        except Exception:  # noqa: BLE001 - table already exists
            pass

    # One entity per key; PartitionKey groups by namespace ("planned"/"provisioned").
    @staticmethod
    def _split(key: str) -> tuple[str, str]:
        ns, _, rest = key.partition(":")
        return ns or "k", rest or key

    def is_done(self, key: str) -> bool:
        from azure.core.exceptions import ResourceNotFoundError

        pk, rk = self._split(key)
        try:
            self._client.get_entity(pk, rk)
            return True
        except ResourceNotFoundError:
            return False

    def mark_done(self, key: str) -> None:
        pk, rk = self._split(key)
        self._client.upsert_entity({"PartitionKey": pk, "RowKey": rk})

    def claim(self, key: str) -> bool:
        """Atomically claim a key: insert-if-absent. Returns False if already claimed.

        `create_entity` fails with ResourceExistsError if the row exists, giving us a
        compare-and-set primitive that's safe across concurrent Function instances — so a
        webhook and the reconciliation poll can't both provision the same ticket.
        """
        from azure.core.exceptions import ResourceExistsError

        pk, rk = self._split(key)
        try:
            self._client.create_entity({"PartitionKey": pk, "RowKey": rk})
            return True
        except ResourceExistsError:
            return False

    def release(self, key: str) -> None:
        from azure.core.exceptions import ResourceNotFoundError

        pk, rk = self._split(key)
        try:
            self._client.delete_entity(pk, rk)
        except ResourceNotFoundError:
            pass


def default_state() -> StateStore:
    """Pick the right store from the environment: Azure Table if configured, else a file.

    Prod: set STATE_TABLE_CONNECTION_STRING (+ optional STATE_TABLE_NAME).
    Dev:  falls back to a JSON file at STATE_PATH (default ./state.json).
    """
    conn = os.environ.get("STATE_TABLE_CONNECTION_STRING")
    if conn:
        return AzureTableState(conn, os.environ.get("STATE_TABLE_NAME", "agentstate"))
    return FileState(os.environ.get("STATE_PATH", "./state.json"))


def planned_key(ticket_id: str) -> str:
    return f"planned:{ticket_id}"


def provisioned_key(ticket_id: str) -> str:
    return f"provisioned:{ticket_id}"


def user_created_key(ticket_id: str) -> str:
    """Marks that THIS ticket already created its user object (enables safe reuse on retry)."""
    return f"user_created:{ticket_id}"
