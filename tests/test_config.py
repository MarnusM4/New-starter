"""Config validation tests — a malformed client file must fail fast."""

import pytest

from lib.config import IdentityPath, load_all_clients, load_client


def test_example_entra_loads():
    cfg = load_client("example-entra")
    assert cfg.identity_path is IdentityPath.ENTRA
    assert cfg.tenant_id  # entra requires a tenant


def test_example_local_ad_loads():
    cfg = load_client("example-local-ad")
    assert cfg.identity_path is IdentityPath.LOCAL_AD
    assert cfg.automation_account and cfg.hybrid_worker_group


def test_unknown_client_raises():
    with pytest.raises(FileNotFoundError):
        load_client("does-not-exist")


def test_all_clients_load_and_validate():
    clients = load_all_clients()
    assert "example-entra" in clients
    for cfg in clients.values():
        cfg.validate_for_path()  # must not raise
