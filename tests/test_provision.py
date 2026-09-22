"""Dispatcher tests: routing per identity_path, using a fake action (no network)."""

from actions.base import ProvisioningPlan
from agent.provision import is_approved, provision, self_approved
from lib.config import load_client


class FakeAction:
    def __init__(self):
        self.calls = []

    def create_user(self, plan):
        self.calls.append("create_user")
        return "user-123"

    def assign_license(self, plan, user_id):
        self.calls.append(("assign_license", user_id))

    def add_groups(self, plan, user_id):
        self.calls.append(("add_groups", user_id))


def _plan(identity_path="entra"):
    return ProvisioningPlan(
        client_id="example-entra" if identity_path == "entra" else "example-local-ad",
        ticket_id="T-1",
        identity_path=identity_path,
        username="ada.lovelace",
        display_name="Ada Lovelace",
        license_skus=["O365_BUSINESS_PREMIUM"],
        groups=["All-Staff"],
        usage_location="GB",
    )


def test_is_approved_reads_status_and_field():
    assert is_approved({"status": "Approved"}) is True
    assert is_approved({"provisioning_approved": True}) is True
    assert is_approved({"status": "new"}) is False


def test_self_approved_detects_requester_equals_approver():
    assert self_approved({"approved_by": "sam@x.io", "reported_by": "sam@x.io"}) is True
    assert self_approved({"approved_by": "SAM@x.io", "requester": "sam@x.io"}) is True
    assert self_approved({"approved_by": "tech@x.io", "reported_by": "sam@x.io"}) is False
    # Can't assert a violation when an identity is unknown -> not flagged here.
    assert self_approved({"status": "approved"}) is False


def test_entra_path_runs_all_steps():
    action = FakeAction()
    result = provision(_plan("entra"), load_client("example-entra"), action=action)
    assert action.calls[0] == "create_user"
    assert result["steps"] == ["create_user", "assign_license", "add_groups"]
    assert result["user_id"] == "user-123"


def test_local_ad_path_creates_user_only_pending_sync():
    action = FakeAction()
    result = provision(_plan("local_ad"), load_client("example-local-ad"), action=action)
    assert action.calls == ["create_user"]
    assert "ad_user_created_pending_sync" in result["steps"]
