"""Run the agent against ONE real Zoho Desk ticket from your own machine.

    python tools/run_ticket.py "#101"          # preview: changes nothing anywhere
    python tools/run_ticket.py "#101" --live   # real run

The ticket can be given as its number shown in Desk ("#101" — quote it, '#' starts a comment
in most shells) or as the long id from the ticket's browser address.

Settings come from `.env` in the repo root (see .env.example).

Preview runs the real decision logic (the same `process_ticket` the Azure Function uses)
against the real ticket, but every outward action is replaced by a printout:
  - no comment or status change on the Desk ticket,
  - no account / licence / group change in Microsoft,
  - no Teams alert, no audit-log entries, no change to the idempotency state.
Reads still happen: the ticket from Desk, and each client tenant's domains from Graph.

--live runs it for real, with the file-backed idempotency state (STATE_PATH, default
./state.json) so re-running is safe exactly as in production. Before approval it posts the
plan and sets "Awaiting Approval"; once a technician sets the ticket to "Approved", the next
--live run creates the account.

Exit code: 0 = fine, 1 = the ticket was (or would be) flagged / provisioning failed,
2 = Zoho settings missing from .env, or no such ticket.
"""

from __future__ import annotations

import argparse
import pathlib
import sys
from contextlib import contextmanager
from typing import Any, Iterator

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FLAG_STATUSES = {"needs_attention", "failed"}


# --------------------------------------------------------------------------- desk wrappers


class PreviewDesk:
    """Reads from the real Desk; prints instead of writing."""

    def __init__(self, desk: Any) -> None:
        self._desk = desk
        self.statuses: list[str] = []

    def get_ticket_raw(self, ticket_id: str) -> dict[str, Any]:
        return self._desk.get_ticket_raw(ticket_id)

    def parse_ticket(self, raw: dict[str, Any]):
        return self._desk.parse_ticket(raw)

    def post_note(self, ticket_id: str, note: str) -> None:
        print(f"\n[PREVIEW] would post internal comment on ticket {ticket_id}:\n{note}\n")

    def update_status(self, ticket_id: str, status: str) -> None:
        self.statuses.append(status)
        print(f"[PREVIEW] would set ticket {ticket_id} status -> {_desk_name(status)}")


class LiveDesk:
    """Passes everything through to the real Desk, remembering the statuses it set."""

    def __init__(self, desk: Any) -> None:
        self._desk = desk
        self.statuses: list[str] = []

    def get_ticket_raw(self, ticket_id: str) -> dict[str, Any]:
        return self._desk.get_ticket_raw(ticket_id)

    def parse_ticket(self, raw: dict[str, Any]):
        return self._desk.parse_ticket(raw)

    def post_note(self, ticket_id: str, note: str) -> None:
        self._desk.post_note(ticket_id, note)
        print(f"\n[LIVE] posted internal comment on ticket {ticket_id}:\n{note}\n")

    def update_status(self, ticket_id: str, status: str) -> None:
        self._desk.update_status(ticket_id, status)
        self.statuses.append(status)
        print(f"[LIVE] set ticket {ticket_id} status -> {_desk_name(status)}")


def _desk_name(status: str) -> str:
    from lib.zoho import desk_status_name

    return desk_status_name(status)


class PreviewState:
    """Reads the real idempotency state; keeps any changes in memory only."""

    def __init__(self, base: Any) -> None:
        self._base = base
        self._added: set[str] = set()
        self._removed: set[str] = set()

    def is_done(self, key: str) -> bool:
        if key in self._removed:
            return False
        return key in self._added or self._base.is_done(key)

    def mark_done(self, key: str) -> None:
        self._added.add(key)
        self._removed.discard(key)

    def claim(self, key: str) -> bool:
        if self.is_done(key):
            return False
        self.mark_done(key)
        return True

    def release(self, key: str) -> None:
        self._added.discard(key)
        self._removed.add(key)


# --------------------------------------------------------------------------- preview hooks


def _preview_provision(plan, config, action=None, **_kw) -> dict[str, Any]:
    steps = ["create_user"]
    if config.identity_path.value == "entra":
        steps += ["assign_license", "add_groups"]
    else:
        steps += ["ad_user_created_pending_sync"]
    print("\n[PREVIEW] would provision now (ticket is approved):")
    print(plan.to_note())
    return {"ticket_id": plan.ticket_id, "user_id": "(preview — not created)", "steps": steps}


def _preview_notify(message: str, *, ticket_id: str | None = None) -> None:
    print(f"[PREVIEW] would send Teams alert: {message}")


def _preview_audit(event: str, ticket_id: str, *, run_id: str | None = None, **fields) -> None:
    detail = " ".join(f"{k}={v}" for k, v in fields.items())
    print(f"[PREVIEW audit] {event} {detail}".rstrip())


@contextmanager
def preview_hooks() -> Iterator[None]:
    """Swap the orchestrator's outward actions for printouts, restoring them afterwards."""
    import agent.orchestrator as orch

    saved = (orch.provision, orch.notify, orch.audit)
    orch.provision, orch.notify, orch.audit = _preview_provision, _preview_notify, _preview_audit
    try:
        yield
    finally:
        orch.provision, orch.notify, orch.audit = saved


# --------------------------------------------------------------------------- summary


def print_summary(desk: Any, ticket_id: str) -> None:
    """What the agent read off the ticket, before it decides anything."""
    from agent.provision import is_approved

    raw = desk.get_ticket_raw(ticket_id)
    print(f"=== Ticket {ticket_id} ===")
    print(f"Subject:   {raw.get('subject', '')}")
    print(f"Desk status: {raw.get('status', '')}   approved: {is_approved(raw)}")
    try:
        ticket = desk.parse_ticket(raw)
    except Exception as exc:  # noqa: BLE001 - shown, then the run reports the flag
        print(f"Parse:     FAILED — {' '.join(str(exc).split())[:300]}")
        return
    print(f"Client:    {ticket.client_id}")
    print(f"Type:      {ticket.ticket_type.value}")
    if ticket.starter:
        for name, value in ticket.starter.model_dump().items():
            if value:
                print(f"  {name}: {value}")
    print()


# --------------------------------------------------------------------------- main


def resolve_ticket_id(desk: Any, ticket: str) -> str:
    """'#101' (the number shown in Desk) -> the API id; anything else is used as the id."""
    ticket = ticket.strip()
    if ticket.startswith("#"):
        return desk.ticket_id_for_number(ticket)
    return ticket


def main(argv: list[str] | None = None, *, desk: Any = None, state: Any = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "ticket",
        help="the ticket: its number as shown in Desk with a # (e.g. '#101'), "
             "or the long id from the ticket's browser address",
    )
    parser.add_argument("--live", action="store_true",
                        help="really write to Desk and provision (default: preview only)")
    args = parser.parse_args(argv)

    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")

    from urllib.parse import urlparse

    import requests

    from agent.orchestrator import process_ticket
    from lib.state import default_state
    from lib.zoho import TicketNotFound, ZohoAuthError, ZohoDeskClient

    real_desk = desk or ZohoDeskClient()
    if desk is None and (real_desk._is_placeholder()
                         or real_desk.org_id.startswith("PLACEHOLDER")):
        print("Zoho Desk credentials are missing: set ZOHO_CLIENT_ID, ZOHO_CLIENT_SECRET, "
              "ZOHO_REFRESH_TOKEN and ZOHO_ORG_ID in .env (see tools/zoho_token.py).")
        return 2
    base_state = state or default_state()

    try:
        ticket_id = resolve_ticket_id(real_desk, args.ticket)
        print("MODE: LIVE — changes will be made\n" if args.live
              else "MODE: PREVIEW — nothing will be changed\n")
        print_summary(real_desk, ticket_id)
    except (TicketNotFound, ZohoAuthError) as exc:
        print(exc)
        return 2
    except requests.HTTPError as exc:
        # Status + URL path only: no query string, headers or body (they can carry secrets).
        resp = exc.response
        where = urlparse(resp.url).path if resp is not None else "?"
        code = resp.status_code if resp is not None else "?"
        print(f"Zoho Desk returned HTTP {code} for {where}. Check ZOHO_ORG_ID and "
              "ZOHO_DESK_BASE_URL in .env, and that the ticket exists.")
        return 2

    if args.live:
        wrapped = LiveDesk(real_desk)
        try:
            process_ticket(ticket_id, desk=wrapped, state=base_state)
        except Exception as exc:  # noqa: BLE001 - orchestrator already flagged + noted it
            print(f"\nProvisioning FAILED: {' '.join(str(exc).split())[:300]}")
            return 1
    else:
        wrapped = PreviewDesk(real_desk)
        with preview_hooks():
            process_ticket(ticket_id, desk=wrapped, state=PreviewState(base_state))

    flagged = FLAG_STATUSES.intersection(wrapped.statuses)
    if flagged:
        print("\nResult: FLAGGED for a technician." if args.live
              else "\nResult: a live run would FLAG this ticket for a technician.")
        return 1
    print("\nResult: OK.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
