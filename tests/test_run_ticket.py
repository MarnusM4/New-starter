"""tools/run_ticket.py: preview never writes anywhere; --live goes through the real core."""

import json

import pytest

import agent.orchestrator as orch
from lib.state import FileState, InMemoryState
from lib.zoho import ZohoDeskClient
from tools import run_ticket

BODY = "Company's Name : example-entra\nNew Starter's Name : Ms., Ada, Lovelace\n"


class FakeDesk(ZohoDeskClient):
    """Real parse_ticket; canned ticket; records any write that reaches it."""

    def __init__(self, raw):
        super().__init__()
        self._raw = raw
        self.notes, self.statuses = [], []

    def get_ticket_raw(self, ticket_id):
        return self._raw

    def post_note(self, ticket_id, note):
        self.notes.append(note)

    def update_status(self, ticket_id, status):
        self.statuses.append(status)


def _raw(**kw):
    raw = {"id": "T1", "subject": "New Starter IT Form", "status": "Open", "description": BODY}
    raw.update(kw)
    return raw


@pytest.fixture
def forbid_side_effects(monkeypatch, tmp_path):
    """Make the real outward actions fail loudly if preview ever lets one through."""
    def boom(*a, **k):
        raise AssertionError("preview must not call this")

    monkeypatch.setattr(orch, "provision", boom)
    monkeypatch.setattr(orch, "notify", boom)
    audit_path = tmp_path / "audit.log"
    monkeypatch.setenv("AUDIT_LOG_PATH", str(audit_path))
    return audit_path


# --------------------------------------------------------------------------- preview


def test_preview_approved_ticket_changes_nothing(forbid_side_effects, tmp_path, capsys):
    desk = FakeDesk(_raw(status="Approved"))
    state_path = tmp_path / "state.json"
    code = run_ticket.main(["T1"], desk=desk, state=FileState(str(state_path)))

    out = capsys.readouterr().out
    assert code == 0
    assert "MODE: PREVIEW" in out
    assert "would provision now" in out
    assert "Username: ada.lovelace" in out
    assert "would set ticket T1 status -> Provisioned" in out
    # Nothing reached Desk, the state file, or the audit log.
    assert desk.notes == [] and desk.statuses == []
    assert not state_path.exists()
    assert not forbid_side_effects.exists()


def test_preview_unapproved_ticket_shows_plan_awaiting_approval(forbid_side_effects, capsys):
    desk = FakeDesk(_raw())
    code = run_ticket.main(["T1"], desk=desk, state=InMemoryState())
    out = capsys.readouterr().out
    assert code == 0
    assert "would post internal comment" in out and "Proposed provisioning plan" in out
    assert "status -> Awaiting Approval" in out
    assert desk.notes == [] and desk.statuses == []


def test_preview_unidentified_client_reports_flag(forbid_side_effects, capsys):
    body = "Your Email address : someone@unknown.example\nNew Starter's Name : Ada, Lovelace\n"
    desk = FakeDesk(_raw(description=body))
    code = run_ticket.main(["T1"], desk=desk, state=InMemoryState())
    out = capsys.readouterr().out
    assert code == 1
    assert "would FLAG" in out
    assert "would send Teams alert" in out
    assert "status -> Needs Attention" in out
    assert desk.notes == [] and desk.statuses == []


def test_preview_respects_existing_state(forbid_side_effects, tmp_path, capsys):
    state_path = tmp_path / "state.json"
    base = FileState(str(state_path))
    base.mark_done("provisioned:T1")
    before = state_path.read_text()
    run_ticket.main(["T1"], desk=FakeDesk(_raw(status="Approved")), state=base)
    out = capsys.readouterr().out
    assert "would provision" not in out          # already done in real state
    assert state_path.read_text() == before      # and the file is untouched


def test_preview_restores_real_hooks(forbid_side_effects):
    real = (orch.provision, orch.notify, orch.audit)
    run_ticket.main(["T1"], desk=FakeDesk(_raw()), state=InMemoryState())
    assert (orch.provision, orch.notify, orch.audit) == real


# --------------------------------------------------------------------------- live


def test_live_unapproved_posts_plan_and_sets_awaiting(monkeypatch, tmp_path):
    monkeypatch.setenv("AUDIT_LOG_PATH", str(tmp_path / "audit.log"))
    desk = FakeDesk(_raw())
    state = InMemoryState()
    code = run_ticket.main(["T1", "--live"], desk=desk, state=state)
    assert code == 0
    assert desk.statuses == ["awaiting_approval"]
    assert "Proposed provisioning plan" in desk.notes[0]
    assert state.is_done("planned:T1")


def test_live_approved_provisions_and_completes(monkeypatch, tmp_path):
    monkeypatch.setenv("AUDIT_LOG_PATH", str(tmp_path / "audit.log"))
    calls = []

    def fake_provision(plan, config, action=None, **kw):
        calls.append(plan.username)
        return {"ticket_id": plan.ticket_id, "user_id": "u1", "steps": ["create_user"]}

    monkeypatch.setattr(orch, "provision", fake_provision)
    desk = FakeDesk(_raw(status="Approved"))
    code = run_ticket.main(["T1", "--live"], desk=desk, state=InMemoryState())
    assert code == 0
    assert calls == ["ada.lovelace"]
    assert desk.statuses == ["completed"]


def test_live_provisioning_failure_exits_nonzero(monkeypatch, tmp_path):
    monkeypatch.setenv("AUDIT_LOG_PATH", str(tmp_path / "audit.log"))
    monkeypatch.setattr(orch, "notify", lambda *a, **k: None)

    def failing(*a, **k):
        raise RuntimeError("Graph said no")

    monkeypatch.setattr(orch, "provision", failing)
    desk = FakeDesk(_raw(status="Approved"))
    assert run_ticket.main(["T1", "--live"], desk=desk, state=InMemoryState()) == 1
    assert desk.statuses == ["failed"]


# --------------------------------------------------------------------------- setup


def test_missing_zoho_settings_exit_2(monkeypatch, capsys):
    for name in ("ZOHO_CLIENT_ID", "ZOHO_CLIENT_SECRET", "ZOHO_REFRESH_TOKEN", "ZOHO_ORG_ID"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(run_ticket, "ROOT", run_ticket.ROOT / "no-such-dir")  # no .env loaded
    assert run_ticket.main(["T1"]) == 2
    assert "credentials are missing" in capsys.readouterr().out


# --------------------------------------------------------------------------- ticket number


def test_hash_number_is_looked_up(forbid_side_effects, capsys):
    class NumberedDesk(FakeDesk):
        def ticket_id_for_number(self, number):
            assert number == "#101"
            return "T1"

    code = run_ticket.main(["#101"], desk=NumberedDesk(_raw()), state=InMemoryState())
    assert code == 0
    assert "=== Ticket T1 ===" in capsys.readouterr().out


def test_unknown_number_exits_2(forbid_side_effects, capsys):
    class EmptyDesk(FakeDesk):
        def ticket_id_for_number(self, number):
            from lib.zoho import TicketNotFound

            raise TicketNotFound("No Desk ticket with number #999")

    assert run_ticket.main(["#999"], desk=EmptyDesk(_raw()), state=InMemoryState()) == 2
    assert "No Desk ticket with number #999" in capsys.readouterr().out


def test_zoho_ticket_id_for_number_request(monkeypatch):
    from lib import zoho

    seen = {}

    class Resp:
        content = b"x"

        def raise_for_status(self):
            return None

        def json(self):
            return {"data": [{"id": "1892000000123456", "ticketNumber": "101"}]}

    def fake_get(url, headers=None, params=None, timeout=None):
        seen["req"] = (url, params)
        return Resp()

    client = ZohoDeskClient()
    monkeypatch.setattr(client, "_headers", lambda: {})
    monkeypatch.setattr(zoho.requests, "get", fake_get)
    assert client.ticket_id_for_number("#101") == "1892000000123456"
    assert seen["req"] == (f"{client.base_url}/api/v1/tickets/search",
                           {"ticketNumber": "101", "limit": 1})


# --------------------------------------------------------------------------- zoho auth errors


@pytest.mark.parametrize("code,hint", [
    ("invalid_code", "generate a new one"),
    ("invalid_client", "ZOHO_CLIENT_ID / ZOHO_CLIENT_SECRET"),
])
def test_rejected_refresh_token_explains_why(monkeypatch, capsys, code, hint):
    """Zoho answers HTTP 200 + {"error": ...}; the tool must say why, not just 'access_token'."""
    from lib import zoho

    class Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"error": code}

    monkeypatch.setattr(zoho.requests, "post", lambda *a, **k: Resp())
    for name, value in {"ZOHO_CLIENT_ID": "1000.cid", "ZOHO_CLIENT_SECRET": "sekrit-value",
                        "ZOHO_REFRESH_TOKEN": "1000.refresh-value", "ZOHO_ORG_ID": "1"}.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(run_ticket, "ROOT", run_ticket.ROOT / "no-such-dir")  # no .env loaded

    assert run_ticket.main(["#101"]) == 2
    out = capsys.readouterr().out
    assert f"Zoho refused the refresh token ({code})" in out
    assert hint in out
    assert "sekrit-value" not in out and "refresh-value" not in out


def test_http_error_is_reported_without_secrets(monkeypatch, capsys):
    import requests

    class FailingDesk(FakeDesk):
        def get_ticket_raw(self, ticket_id):
            resp = requests.Response()
            resp.status_code = 401
            resp.url = "https://desk.zoho.com/api/v1/tickets/T1?secret=abc"
            raise requests.HTTPError(response=resp)

    assert run_ticket.main(["T1"], desk=FailingDesk(_raw()), state=InMemoryState()) == 2
    out = capsys.readouterr().out
    assert "HTTP 401 for /api/v1/tickets/T1" in out
    assert "secret=abc" not in out
