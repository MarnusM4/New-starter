"""Append-only audit logging.

Every decision and action ties back to a ticket id. In Phase A this writes structured
JSON lines to a local file; in production point AUDIT_LOG_PATH at durable storage
(or swap for Azure Table/Log Analytics).
"""

from __future__ import annotations

import datetime as _dt
import json
import os
from typing import Any


def new_run_id() -> str:
    """Correlation id for one ticket-processing run, threaded through its audit events."""
    import uuid

    return uuid.uuid4().hex[:12]


def audit(event: str, ticket_id: str, *, run_id: str | None = None, **fields: Any) -> None:
    record = {
        "ts": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "event": event,
        "ticket_id": ticket_id,
        **({"run_id": run_id} if run_id else {}),
        **fields,
    }
    line = json.dumps(record, default=str)
    path = os.environ.get("AUDIT_LOG_PATH", "./audit.log")
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")
    print(f"[AUDIT] {line}")
