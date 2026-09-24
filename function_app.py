"""Azure Functions app — Zoho Desk webhook front door + reconciliation poll.

- zoho_webhook (HTTP): real-time trigger. Verifies the Desk webhook shared-secret token,
  then hands the ticket id to the trigger-agnostic orchestrator (Phase A–C).
- reconcile_poll (timer): safety net. Periodically re-drives open starter/leaver tickets
  through the same core; durable idempotency means already-handled tickets are skipped.

Run locally:  func start   (requires Azure Functions Core Tools + local.settings.json)
"""

from __future__ import annotations

import json
import logging

import azure.functions as func

from agent.orchestrator import process_ticket
from agent.reconcile import run_reconciliation
from agent.webhook import (
    SIGNATURE_HEADER,
    TIMESTAMP_HEADER,
    extract_ticket_id,
    verify_signature,
)

app = func.FunctionApp()


@app.route(route="zoho-webhook", auth_level=func.AuthLevel.FUNCTION)
def zoho_webhook(req: func.HttpRequest) -> func.HttpResponse:
    raw = req.get_body()

    if not verify_signature(
        raw,
        req.headers.get(SIGNATURE_HEADER),
        req.headers.get(TIMESTAMP_HEADER),
    ):
        logging.warning("Rejected webhook: bad/missing signature")
        return func.HttpResponse("invalid signature", status_code=401)

    try:
        payload = json.loads(raw or b"{}")
    except json.JSONDecodeError:
        return func.HttpResponse("bad json", status_code=400)

    ticket_id = extract_ticket_id(payload)
    if not ticket_id:
        return func.HttpResponse("no ticket id in payload", status_code=400)

    try:
        plan = process_ticket(ticket_id)
    except Exception:  # noqa: BLE001 - log and 500 so Desk retries
        logging.exception("Failed processing ticket %s", ticket_id)
        return func.HttpResponse("processing error", status_code=500)

    body = {"ticket_id": ticket_id, "status": "processed", "planned": plan is not None}
    return func.HttpResponse(json.dumps(body), mimetype="application/json", status_code=200)


# Every 15 minutes. Adjust the CRON as needed; the poll is cheap and idempotent.
@app.timer_trigger(schedule="0 */15 * * * *", arg_name="timer", run_on_startup=False)
def reconcile_poll(timer: func.TimerRequest) -> None:
    summary = run_reconciliation()
    logging.info("Reconciliation summary: %s", summary)
