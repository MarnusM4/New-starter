"""Orchestrator tests: plan building + the approval gate routing (no network)."""

from agent import orchestrator
from agent.orchestrator import build_plan, process_ticket
from lib.config import load_client
from lib.state import InMemoryState
from lib.ticket import StarterDetails, Ticket, TicketType


class FakeDesk:
    """Stand-in for ZohoDeskClient: serves a canned ticket, records notes + statuses."""

    def __init__(self, raw):
        self._raw = raw
        self.notes: list[tuple[str, str]] = []
        self.statuses: list[str] = []

    def get_ticket_raw(self, ticket_id):
        return self._raw

    def parse_ticket(self, raw):
        return Ticket(
            ticket_id=raw["id"],
            client_id=raw["client_ref"],
            ticket_type=TicketType(raw["type"]),
            starter=StarterDetails(**raw["user_info"]),
        )

    def post_note(self, ticket_id, note):
        self.notes.append((ticket_id, note))

    def update_status(self, ticket_id, status):
        self.statuses.append(status)


def _raw(**overrides):
    raw = {
        "id": "T-1001",
        "client_ref": "example-entra",
        "type": "starter",
        "user_info": {"first_name": "Ada", "last_name": "Lovelace", "role": "Sales"},
    }
    raw.update(overrides)
    return raw


def test_build_plan_maps_role_groups():
    ticket = FakeDesk(_raw()).parse_ticket(_raw())
    plan = build_plan(ticket, load_client("example-entra"))
    assert plan.username == "ada.lovelace"
    assert plan.identity_path == "entra"
    assert "All-Staff" in plan.groups
    assert "CRM-Users" in plan.groups


def test_unapproved_ticket_posts_plan_and_does_not_provision(monkeypatch):
    called = {"provision": 0}
    monkeypatch.setattr(orchestrator, "provision", lambda *a, **k: called.__setitem__("provision", 1))
    fake = FakeDesk(_raw())  # no approval -> approval_required default true
    plan = process_ticket("T-1001", desk=fake, state=InMemoryState())
    assert plan is not None
    assert called["provision"] == 0
    assert len(fake.notes) == 1
    assert "Proposed provisioning plan" in fake.notes[0][1]
    assert fake.statuses == ["awaiting_approval"]


def test_unknown_client_flags_for_human(monkeypatch):
    monkeypatch.setattr(orchestrator, "provision", lambda *a, **k: None)
    fake = FakeDesk(_raw(client_ref="9999-unmapped"))
    plan = process_ticket("T-1001", desk=fake, state=InMemoryState())
    assert plan is None
    assert fake.statuses == ["needs_attention"]
    assert "Couldn't match this request" in fake.notes[0][1]


def test_approved_ticket_writes_completed_status(monkeypatch):
    monkeypatch.setattr(
        orchestrator, "provision",
        lambda plan, config, action=None, **kw: {"ticket_id": plan.ticket_id, "user_id": "u1",
                                                 "steps": ["create_user"]},
    )
    fake = FakeDesk(_raw(status="approved"))
    process_ticket("T-1001", desk=fake, state=InMemoryState())
    assert fake.statuses == ["completed"]


def test_duplicate_create_posts_plan_once(monkeypatch):
    monkeypatch.setattr(orchestrator, "provision", lambda *a, **k: None)
    fake = FakeDesk(_raw())
    shared = InMemoryState()  # same store across deliveries (as durable storage would be)
    process_ticket("T-1001", desk=fake, state=shared)
    process_ticket("T-1001", desk=fake, state=shared)
    assert len(fake.notes) == 1  # not posted twice


def test_approved_ticket_provisions_once(monkeypatch):
    calls = {"n": 0}

    def fake_provision(plan, config, action=None, **kw):
        calls["n"] += 1
        return {"ticket_id": plan.ticket_id, "user_id": "u1", "steps": ["create_user"]}

    monkeypatch.setattr(orchestrator, "provision", fake_provision)
    fake = FakeDesk(_raw(status="approved"))
    shared = InMemoryState()
    process_ticket("T-1001", desk=fake, state=shared)
    process_ticket("T-1001", desk=fake, state=shared)  # re-delivery must not provision again
    assert calls["n"] == 1


def test_self_approval_is_rejected_and_does_not_provision(monkeypatch):
    """Separation of duties: requester == approver must not pass the gate."""
    called = {"provision": 0}
    monkeypatch.setattr(orchestrator, "provision", lambda *a, **k: called.__setitem__("provision", 1))
    fake = FakeDesk(_raw(status="approved", approved_by="sam@x.io", reported_by="sam@x.io"))
    process_ticket("T-1001", desk=fake, state=InMemoryState())
    assert called["provision"] == 0
    assert fake.statuses == ["needs_attention"]
    assert "separation of duties" in fake.notes[0][1].lower()


def test_invalid_username_flags_for_human(monkeypatch):
    """A crafted, out-of-policy desired_username must not reach provisioning."""
    called = {"provision": 0}
    monkeypatch.setattr(orchestrator, "provision", lambda *a, **k: called.__setitem__("provision", 1))
    bad = _raw(status="approved")
    bad["user_info"] = {"first_name": "Ada", "last_name": "Lovelace",
                        "desired_username": "admin' or '1'='1"}
    fake = FakeDesk(bad)
    plan = process_ticket("T-1001", desk=fake, state=InMemoryState())
    assert plan is None
    assert called["provision"] == 0
    assert fake.statuses == ["needs_attention"]


def test_missing_required_fields_flags_for_human(monkeypatch):
    """An empty starter name fails validation and is flagged, not provisioned."""
    monkeypatch.setattr(orchestrator, "provision", lambda *a, **k: None)
    bad = _raw(status="approved")
    bad["user_info"] = {"first_name": "", "last_name": ""}
    fake = FakeDesk(bad)
    plan = process_ticket("T-1001", desk=fake, state=InMemoryState())
    assert plan is None
    assert fake.statuses == ["needs_attention"]


def test_unclear_ticket_type_flags_for_human(monkeypatch):
    """A subject that isn't clearly starter or leaver must never provision on a guess."""
    called = {"provision": 0}
    monkeypatch.setattr(orchestrator, "provision", lambda *a, **k: called.__setitem__("provision", 1))
    fake = FakeDesk(_raw(type="unknown", status="approved"))
    plan = process_ticket("T-1001", desk=fake, state=InMemoryState())
    assert plan is None
    assert called["provision"] == 0
    assert fake.statuses == ["needs_attention"]
    assert "starter or a leaver" in fake.notes[0][1]
