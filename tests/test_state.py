"""State store tests: in-memory + file-backed persistence."""

from lib.state import FileState, InMemoryState, planned_key, provisioned_key


def test_inmemory_marks_and_reads():
    s = InMemoryState()
    assert not s.is_done("a")
    s.mark_done("a")
    assert s.is_done("a")


def test_file_state_persists_across_instances(tmp_path):
    path = str(tmp_path / "state.json")
    s1 = FileState(path)
    s1.mark_done(provisioned_key("T-1"))
    # A fresh instance (e.g. a different Function invocation) sees the same state.
    s2 = FileState(path)
    assert s2.is_done(provisioned_key("T-1"))
    assert not s2.is_done(planned_key("T-1"))


def test_inmemory_claim_is_exclusive():
    s = InMemoryState()
    assert s.claim("provisioned:T-1") is True   # first claim wins
    assert s.claim("provisioned:T-1") is False  # second is refused (no double-provision)
    s.release("provisioned:T-1")
    assert s.claim("provisioned:T-1") is True    # released -> claimable again (retry)


def test_file_state_claim_is_exclusive_across_instances(tmp_path):
    path = str(tmp_path / "state.json")
    assert FileState(path).claim(provisioned_key("T-9")) is True
    # A concurrent instance reading the same file must lose the race.
    assert FileState(path).claim(provisioned_key("T-9")) is False
