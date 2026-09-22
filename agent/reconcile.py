"""Reconciliation poll (Phase D) — safety net for missed/failed webhooks.

A timer-triggered Function runs this periodically. It lists open starter/leaver tickets
and feeds each through the SAME orchestrator core the webhook uses. Idempotency (the
durable state store) means tickets already handled are skipped, so the poll is safe to run
as often as you like — it only catches stragglers.

One ticket failing must not abort the batch, so per-ticket errors are caught and audited;
the run continues and returns a summary.
"""

from __future__ import annotations

import sys
import pathlib
from typing import Any

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from agent.orchestrator import process_ticket  # noqa: E402
from lib.audit import audit, new_run_id  # noqa: E402
from lib.halo import HaloClient  # noqa: E402
from lib.state import StateStore  # noqa: E402


def run_reconciliation(
    halo: HaloClient | None = None,
    state: StateStore | None = None,
) -> dict[str, Any]:
    halo = halo or HaloClient()
    run_id = new_run_id()

    ticket_ids = halo.list_open_starter_leaver_ticket_ids()
    audit("reconcile.start", "-", run_id=run_id, candidate_count=len(ticket_ids))

    processed, failed = 0, 0
    for ticket_id in ticket_ids:
        try:
            process_ticket(ticket_id, halo=halo, state=state)
            processed += 1
        except Exception as exc:  # noqa: BLE001 - one bad ticket must not stop the batch
            failed += 1
            audit("reconcile.ticket_failed", ticket_id, run_id=run_id, error=str(exc))

    summary = {"candidates": len(ticket_ids), "processed": processed, "failed": failed}
    audit("reconcile.done", "-", run_id=run_id, **summary)
    return summary
