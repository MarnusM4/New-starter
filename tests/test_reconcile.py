"""Reconciliation poll tests: drives the core, survives a bad ticket, no double work."""

from agent import reconcile
from lib.state import InMemoryState


class FakeHalo:
    def __init__(self, ids):
        self._ids = ids

    def list_open_starter_leaver_ticket_ids(self):
        return self._ids


def test_reconcile_processes_all_candidates(monkeypatch):
    seen = []
    monkeypatch.setattr(reconcile, "process_ticket", lambda tid, halo, state: seen.append(tid))
    summary = reconcile.run_reconciliation(halo=FakeHalo(["T-1", "T-2"]), state=InMemoryState())
    assert seen == ["T-1", "T-2"]
    assert summary == {"candidates": 2, "processed": 2, "failed": 0}


def test_reconcile_continues_past_a_failing_ticket(monkeypatch):
    def flaky(tid, halo, state):
        if tid == "T-2":
            raise RuntimeError("boom")

    monkeypatch.setattr(reconcile, "process_ticket", flaky)
    summary = reconcile.run_reconciliation(
        halo=FakeHalo(["T-1", "T-2", "T-3"]), state=InMemoryState()
    )
    assert summary == {"candidates": 3, "processed": 2, "failed": 1}
