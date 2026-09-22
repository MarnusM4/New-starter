"""EntraAction tests with a fake Graph transport (no network), incl. idempotency."""

import pytest

from actions.base import ProvisioningPlan, UserCollisionError
from actions.entra.action import EntraAction


class FakeGraph:
    """Records POSTs; serves canned GETs. Configurable existing user/licenses/groups."""

    def __init__(self, existing_user=None, existing_licenses=None, existing_member_of=None):
        self.posts = []
        self._existing_user = existing_user          # id or None
        self._existing_licenses = existing_licenses or []   # skuIds
        self._existing_member_of = existing_member_of or []  # group ids

    def get(self, path, params=None):
        if path == "/domains":
            return {"value": [{"id": "contoso.com", "isDefault": True}]}
        if path == "/subscribedSkus":
            return {"value": [{"skuPartNumber": "O365_BUSINESS_PREMIUM", "skuId": "sku-guid-1"}]}
        if path == "/users" and params and "userPrincipalName" in params.get("$filter", ""):
            return {"value": [{"id": self._existing_user}] if self._existing_user else []}
        if path.endswith("/licenseDetails"):
            return {"value": [{"skuId": s} for s in self._existing_licenses]}
        if path.endswith("/memberOf"):
            return {"value": [{"id": g} for g in self._existing_member_of]}
        if path == "/groups":
            name = params["$filter"].split("'")[1]
            return {"value": [{"id": f"group-{name}"}]}
        raise AssertionError(f"unexpected GET {path} {params}")

    def post(self, path, json=None):
        self.posts.append((path, json))
        if path == "/users":
            return {"id": "new-user-id"}
        return None


def _plan():
    return ProvisioningPlan(
        client_id="example-entra",
        ticket_id="T-1",
        identity_path="entra",
        username="ada.lovelace",
        display_name="Ada Lovelace",
        license_skus=["O365_BUSINESS_PREMIUM"],
        groups=["All-Staff", "CRM-Users"],
        usage_location="GB",
    )


def test_create_user_builds_correct_upn_and_body():
    g = FakeGraph()
    uid = EntraAction(tenant_id="t", transport=g).create_user(_plan())
    assert uid == "new-user-id"
    path, body = g.posts[0]
    assert path == "/users"
    assert body["userPrincipalName"] == "ada.lovelace@contoso.com"
    assert body["passwordProfile"]["forceChangePasswordNextSignIn"] is True


def test_create_user_uses_config_upn_suffix():
    g = FakeGraph()
    plan = _plan().model_copy(update={"upn_suffix": "acme.com"})
    EntraAction(tenant_id="t", transport=g).create_user(plan)
    assert g.posts[0][1]["userPrincipalName"] == "ada.lovelace@acme.com"


def test_create_user_refuses_unexpected_existing_user():
    """An existing account we didn't create for this ticket is a collision -> refuse."""
    g = FakeGraph(existing_user="already-there")
    with pytest.raises(UserCollisionError):
        EntraAction(tenant_id="t", transport=g).create_user(_plan())
    assert g.posts == []  # nothing created or mutated


def test_create_user_reuses_existing_when_allowed():
    """Safe re-run: when the orchestrator confirms we created it before, reuse it."""
    g = FakeGraph(existing_user="already-there")
    plan = _plan().model_copy(update={"allow_existing_user": True})
    uid = EntraAction(tenant_id="t", transport=g).create_user(plan)
    assert uid == "already-there"
    assert g.posts == []  # reused, not re-created


def test_assign_license_resolves_and_skips_existing():
    g = FakeGraph()
    EntraAction(tenant_id="t", transport=g).assign_license(_plan(), "new-user-id")
    path, body = g.posts[-1]
    assert path == "/users/new-user-id/assignLicense"
    assert body["addLicenses"][0]["skuId"] == "sku-guid-1"

    g2 = FakeGraph(existing_licenses=["sku-guid-1"])  # already licensed
    EntraAction(tenant_id="t", transport=g2).assign_license(_plan(), "new-user-id")
    assert g2.posts == []  # nothing to add


def test_add_groups_skips_existing_membership():
    g = FakeGraph(existing_member_of=["group-All-Staff"])
    EntraAction(tenant_id="t", transport=g).add_groups(_plan(), "new-user-id")
    ref_posts = {p[0] for p in g.posts if "/members/$ref" in p[0]}
    assert ref_posts == {"/groups/group-CRM-Users/members/$ref"}  # All-Staff skipped
