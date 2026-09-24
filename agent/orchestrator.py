"""Per-ticket orchestrator core (trigger-agnostic).

This is the brain that both the webhook front door and the reconciliation poll call:
read ticket -> resolve client -> build a provisioning plan -> if approved, provision via
the constrained action layer, else post the plan and wait for approval (Phase B).
"""

from __future__ import annotations

import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from pydantic import ValidationError  # noqa: E402

from actions.base import ProvisioningPlan  # noqa: E402
from agent.provision import (  # noqa: E402
    approver,
    is_approved,
    provision,
    result_note,
    self_approved,
)
from lib.audit import audit, new_run_id  # noqa: E402
from lib.config import ClientConfig, UnknownClientError, resolve_config  # noqa: E402
from lib.notify import notify  # noqa: E402
from lib.zoho import (  # noqa: E402
    STATUS_AWAITING_APPROVAL,
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_NEEDS_ATTENTION,
    ZohoDeskClient,
)
from lib.state import (  # noqa: E402
    StateStore,
    default_state,
    planned_key,
    provisioned_key,
    user_created_key,
)
from lib.ticket import InvalidTicketData, Ticket, TicketType, validate_username  # noqa: E402


def _safe_detail(exc: Exception, limit: int = 200) -> str:
    """A single-line, length-capped error string safe to surface off-box.

    Raw exception text can carry internal detail (URLs, identifiers) and shouldn't be
    written verbatim into a client-visible ticket note or an external alert channel.
    """
    msg = " ".join(str(exc).split())
    return msg if len(msg) <= limit else msg[:limit] + "…"


def build_username(ticket: Ticket, username_format: str = "{first}.{last}") -> str:
    """Derive a username from validated ticket fields + the client's naming convention.

    An explicit desired_username on the ticket wins; otherwise apply the client's
    username_format template. Tokens: {first} {last} {first_initial} {last_initial}.

    Whichever source is used, the result is validated against the username policy
    (lib.ticket.validate_username) before it can flow into account creation — raising
    InvalidTicketData if a crafted ticket field falls outside the allow-list.
    """
    s = ticket.starter
    assert s is not None
    if s.desired_username:
        candidate = s.desired_username.strip().lower().replace(" ", "")
    else:
        name = username_format.format(
            first=s.first_name,
            last=s.last_name,
            first_initial=s.first_name[:1],
            last_initial=s.last_name[:1],
        )
        candidate = name.strip(".").lower().replace(" ", "")
    return validate_username(candidate)


def build_plan(ticket: Ticket, config: ClientConfig) -> ProvisioningPlan:
    """Turn a validated ticket + client config into a concrete provisioning plan."""
    config.validate_for_path()
    s = ticket.starter
    assert s is not None

    groups = list(config.default_groups)
    if s.role and s.role in config.role_group_map:
        groups.extend(config.role_group_map[s.role])

    username = build_username(ticket, config.username_format)
    display_name = s.display_name or f"{s.first_name} {s.last_name}".strip()

    return ProvisioningPlan(
        client_id=config.client_id,
        ticket_id=ticket.ticket_id,
        identity_path=config.identity_path.value,
        username=username,
        display_name=display_name,
        license_skus=list(config.license_skus),
        groups=groups,
        usage_location=config.usage_location,
        upn_suffix=config.upn_suffix,
    )


# Default durable store (Azure Table in prod, file in dev — see lib.state.default_state).
# Built lazily so importing this module never requires storage to be configured.
# Idempotency keys: planned:<id> (plan posted once) and provisioned:<id>
# (SAFETY-CRITICAL — never provision the same ticket twice).
_default_state: StateStore | None = None


def _get_default_state() -> StateStore:
    global _default_state
    if _default_state is None:
        _default_state = default_state()
    return _default_state


def process_ticket(
    ticket_id: str,
    desk: ZohoDeskClient | None = None,
    state: StateStore | None = None,
) -> ProvisioningPlan | None:
    """Entry point for a single ticket.

    Phase C: every outcome (awaiting approval, provisioned, failed, unknown client, no
    action) writes back to the ticket — a note + a status — and is recorded in the audit
    log under a single run id.

    Idempotent: duplicate create deliveries post the plan once; provisioning runs at most
    once per ticket. An approval update re-enters here and proceeds to provisioning.
    """
    desk = desk or ZohoDeskClient()
    state = state or _get_default_state()
    run_id = new_run_id()

    audit("ticket.received", ticket_id, run_id=run_id)
    raw = desk.get_ticket_raw(ticket_id)
    try:
        ticket = desk.parse_ticket(raw)
    except ValidationError as exc:
        # Untrusted ticket failed schema validation (e.g. missing/empty required fields).
        audit("ticket.invalid", ticket_id, run_id=run_id, error=_safe_detail(exc))
        desk.post_note(
            ticket_id,
            "⚠️ Ticket is missing required new-starter details (e.g. first/last name). "
            "No action taken.",
        )
        desk.update_status(ticket_id, STATUS_NEEDS_ATTENTION)
        notify(f"Ticket {ticket_id}: invalid/missing starter details — needs attention.")
        return None
    audit("ticket.parsed", ticket_id, run_id=run_id,
          client_id=ticket.client_id, type=ticket.ticket_type.value)

    if ticket.ticket_type is TicketType.UNKNOWN:
        # The subject didn't clearly say starter or leaver — never provision on a guess.
        audit("ticket.type_unknown", ticket_id, run_id=run_id)
        desk.post_note(
            ticket_id,
            "⚠️ Couldn't tell from the subject whether this is a starter or a leaver request. "
            "No action taken.",
        )
        desk.update_status(ticket_id, STATUS_NEEDS_ATTENTION)
        notify(f"Ticket {ticket_id}: starter/leaver type unclear from subject — needs attention.")
        return None

    if ticket.ticket_type is not TicketType.STARTER:
        # Leaver handling arrives in Phase E.
        audit("ticket.skipped_non_starter", ticket_id, run_id=run_id, type=ticket.ticket_type.value)
        desk.post_note(ticket_id, "Leaver tickets are not automated yet (Phase E).")
        return None

    if state.is_done(provisioned_key(ticket_id)):
        audit("ticket.already_provisioned", ticket_id, run_id=run_id)
        return None

    # Resolve the identified client to its config. Unidentified/ambiguous -> flag a human.
    try:
        config = resolve_config(ticket.client_id)
    except UnknownClientError:
        audit("client.unknown", ticket_id, run_id=run_id, desk_client=ticket.client_id)
        desk.post_note(
            ticket_id,
            f"⚠️ Couldn't match this request to a set-up client ({ticket.client_id}). "
            "Check the client has a config file in clients/ (its email domains are read from "
            "its Microsoft tenant), or add a company-name alias to clients/_lookup.yaml. "
            "No action taken.",
        )
        desk.update_status(ticket_id, STATUS_NEEDS_ATTENTION)
        notify(f"Ticket {ticket_id}: client not identified ({ticket.client_id}) — needs attention.")
        return None

    # Build the plan — this validates ticket-derived inputs (e.g. the username) against
    # policy. Out-of-policy input flags a human rather than provisioning something odd.
    try:
        plan = build_plan(ticket, config)
    except InvalidTicketData as exc:
        audit("plan.invalid_input", ticket_id, run_id=run_id, error=_safe_detail(exc))
        desk.post_note(
            ticket_id,
            f"⚠️ Ticket data could not be safely used to provision: {_safe_detail(exc)}. "
            "No action taken.",
        )
        desk.update_status(ticket_id, STATUS_NEEDS_ATTENTION)
        notify(f"Ticket {ticket_id}: invalid ticket data — needs attention.")
        return None
    audit("plan.built", ticket_id, run_id=run_id, client_id=plan.client_id,
          identity_path=plan.identity_path, username=plan.username)

    # Separation of duties: an approval where the approver is also the requester is not a
    # valid approval. Flag it instead of silently treating it as unapproved.
    if is_approved(raw) and self_approved(raw):
        audit("approval.self_approval_rejected", ticket_id, run_id=run_id,
              approved_by=approver(raw))
        desk.post_note(
            ticket_id,
            "⚠️ Approval rejected: the approver cannot be the same person who requested "
            "the account (separation of duties). A different authorised approver is required.",
        )
        desk.update_status(ticket_id, STATUS_NEEDS_ATTENTION)
        notify(f"Ticket {ticket_id}: self-approval rejected — needs a separate approver.")
        return plan

    # Approval gate: provision only when approved (or the client opted out of approval).
    if config.approval_required and not is_approved(raw):
        if not state.is_done(planned_key(ticket_id)):
            desk.post_note(ticket_id, plan.to_note())
            desk.update_status(ticket_id, STATUS_AWAITING_APPROVAL)
            state.mark_done(planned_key(ticket_id))
            audit("plan.posted_awaiting_approval", ticket_id, run_id=run_id)
        else:
            audit("plan.duplicate_skipped", ticket_id, run_id=run_id)
        return plan

    # Approved (or no approval required) -> provision via the constrained action layer.
    # Atomically claim the provisioned marker FIRST so a concurrent webhook + poll (or a
    # duplicate delivery) can't both provision. The loser of the race simply returns.
    if not state.claim(provisioned_key(ticket_id)):
        audit("provision.already_in_progress", ticket_id, run_id=run_id)
        return plan

    audit("provision.authorized", ticket_id, run_id=run_id, approved_by=approver(raw))
    # Reuse an existing account only if we recorded creating it for THIS ticket before.
    plan.allow_existing_user = state.is_done(user_created_key(ticket_id))
    try:
        result = provision(
            plan,
            config,
            on_user_created=lambda: state.mark_done(user_created_key(ticket_id)),
        )
    except Exception as exc:  # noqa: BLE001 - write back + flag, then re-raise to surface
        # Release the claim so the reconciliation poll can retry a transient failure.
        state.release(provisioned_key(ticket_id))
        audit("provision.failed", ticket_id, run_id=run_id, error=_safe_detail(exc, 500))
        desk.post_note(
            ticket_id,
            f"❌ Provisioning failed (ref {run_id}). Flagged for a technician.",
        )
        desk.update_status(ticket_id, STATUS_FAILED)
        notify(f"Ticket {ticket_id} (run {run_id}): provisioning FAILED — {_safe_detail(exc)}")
        raise

    # Success: the provisioned marker claimed above stays set (idempotency complete).
    desk.post_note(ticket_id, result_note(result))
    desk.update_status(ticket_id, STATUS_COMPLETED)
    audit("ticket.provisioned", ticket_id, run_id=run_id, steps=result["steps"])
    return plan
