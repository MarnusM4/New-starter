"""Client identification (company name + auto-discovered email domains) and subject
classification. No network: tenant domain discovery is faked via set_domain_fetcher.
"""

import pytest

from lib import config, graph
from lib.config import (
    AmbiguousClientError,
    UnknownClientError,
    build_domain_index,
    domain_index,
    identify_client,
    load_client,
    resolve_config,
    set_domain_fetcher,
)
from lib.ticket import TicketType
from lib.zoho import ZohoDeskClient, classify_subject

# example-entra and example-local-ad stand in for two real clients.
TENANT_DOMAINS = {
    "example-entra": ["naturalselection.travel", "naturalselection.co.za"],
    "example-local-ad": ["portlandquarry.co.za"],
}


@pytest.fixture
def tenants():
    set_domain_fetcher(lambda cfg: TENANT_DOMAINS.get(cfg.client_id, []))


# --------------------------------------------------------------------------- domains


def test_client_with_two_domains_matches_from_either(tenants):
    assert identify_client(None, "Your Email address : q@naturalselection.travel") == "example-entra"
    assert identify_client(None, "New Starter's NS Email Address : p@naturalselection.co.za") == (
        "example-entra"
    )


def test_msp_helpdesk_domain_in_email_text_is_ignored(tenants):
    body = (
        "forward any changes to Flawless IT Solutions Support at helpdesk@flawlessit.co.za\n"
        "Requesters Email address : andre@portlandquarry.co.za\n"
    )
    assert identify_client(None, body) == "example-local-ad"


def test_unknown_domain_raises_unknown():
    with pytest.raises(UnknownClientError):
        identify_client(None, "Your Email address : someone@gmail.com")


def test_company_and_domain_disagree_is_ambiguous(tenants):
    # "example-entra" is a company alias in _lookup.yaml; the domain belongs to the other client.
    with pytest.raises(AmbiguousClientError):
        identify_client("example-entra", "Email : andre@portlandquarry.co.za")


def test_domain_claimed_by_two_clients_is_ambiguous():
    set_domain_fetcher(lambda cfg: ["shared.com"])
    with pytest.raises(AmbiguousClientError):
        identify_client(None, "Email : x@shared.com")


def test_unreachable_tenant_is_skipped_not_fatal():
    def fetch(cfg):
        if cfg.client_id == "example-local-ad":
            raise RuntimeError("tenant unreachable")
        return ["naturalselection.travel"]

    set_domain_fetcher(fetch)
    assert identify_client(None, "Email : q@naturalselection.travel") == "example-entra"


def test_domain_index_is_cached(monkeypatch):
    calls = {"n": 0}

    def fetch(cfg):
        calls["n"] += 1
        return []

    set_domain_fetcher(fetch)
    domain_index()
    first = calls["n"]
    domain_index()
    assert calls["n"] == first  # second call served from cache


def test_manual_email_domains_override_is_indexed(monkeypatch):
    real_load = config.load_client

    def load_with_override(stem):
        cfg = real_load(stem)
        if stem == "example-entra":
            return cfg.model_copy(update={"email_domains": ["legacy-brand.com"]})
        return cfg

    monkeypatch.setattr(config, "load_client", load_with_override)
    assert build_domain_index(lambda cfg: [])["legacy-brand.com"] == {"example-entra"}


def test_graph_discovery_keeps_only_verified_domains(monkeypatch):
    class FakeTransport:
        def __init__(self, tenant_id):
            assert tenant_id == "tenant-guid"

        def get(self, path, params=None):
            assert path == "/domains"
            return {"value": [
                {"id": "NaturalSelection.travel", "isVerified": True},
                {"id": "pending.example", "isVerified": False},
            ]}

    monkeypatch.setattr(graph, "RealGraphTransport", FakeTransport)
    cfg = load_client("example-entra").model_copy(update={"tenant_id": "tenant-guid"})
    assert config.graph_verified_domains(cfg) == ["naturalselection.travel"]


def test_placeholder_tenant_is_not_queried():
    assert config.graph_verified_domains(load_client("example-entra")) == []


# --------------------------------------------------------------------------- safety


@pytest.mark.parametrize("bad", ["../x", "../../etc/passwd", "_schema", "_lookup", "a/b"])
def test_unsafe_company_text_never_becomes_a_path(bad):
    with pytest.raises(UnknownClientError):
        resolve_config(bad)
    with pytest.raises(UnknownClientError):
        identify_client(bad, "", index={})


def test_load_client_rejects_path_like_ids():
    with pytest.raises(FileNotFoundError):
        load_client("../x")


def test_company_alias_match_is_case_insensitive():
    # Company names typed on forms vary in case/whitespace; a real alias still resolves.
    assert resolve_config("Example-Entra ").client_id == "example-entra"


# --------------------------------------------------------------------------- end to end


def test_form_without_company_field_identified_by_domain(tenants):
    body = (
        "Your name : Quinton, Miller\n"
        "Your Email address : quintonm@naturalselection.travel\n"
        "New Starter's Name : Ms., Paula, Potgieter\n"
        "New Starter's NS Email Address : paulap@naturalselection.travel\n"
        "Job Title : Digital Marketing Manager\n"
    )
    raw = {"id": "1", "subject": "New Starter IT Form for Paula Potgieter", "description": body}
    ticket = ZohoDeskClient().parse_ticket(raw)
    assert ticket.client_id == "example-entra"
    assert ticket.ticket_type is TicketType.STARTER
    assert ticket.starter.first_name == "Paula"


def test_ambiguous_ticket_gets_readable_marker(tenants):
    body = (
        "Company's Name : example-entra\n"
        "Email : andre@portlandquarry.co.za\n"
        "New Starter's Name : Ada, Lovelace\n"
    )
    ticket = ZohoDeskClient().parse_ticket({"id": "1", "subject": "Onboarding", "description": body})
    assert ticket.client_id.startswith("ambiguous:")
    assert "portlandquarry.co.za" in ticket.client_id


# --------------------------------------------------------------------------- subjects


@pytest.mark.parametrize("subject", [
    "Onboarding",
    "Portland Holding User Onboarding Form",
    "New Starter IT Form",
    "New User",
    "new-user request for Paula",
    "New Employee",
])
def test_starter_subjects(subject):
    assert classify_subject(subject) is TicketType.STARTER


@pytest.mark.parametrize("subject", [
    "Offboarding",
    "Off-boarding form",
    "Leaver Form",
    "Staff Exit Form",
    "Termination notice",
])
def test_leaver_subjects(subject):
    assert classify_subject(subject) is TicketType.LEAVER


@pytest.mark.parametrize("subject", [
    "Laptop request",
    "New user / leaver",       # both -> unclear
    "Userland onboardingx",    # no whole-word match
    "",
])
def test_unclear_subjects(subject):
    assert classify_subject(subject) is TicketType.UNKNOWN


def test_per_client_extra_keyword():
    cfg = load_client("example-entra").model_copy(update={"starter_subject_keywords": ["it request"]})
    assert classify_subject("IT Request - Paula", cfg) is TicketType.STARTER
    assert classify_subject("IT Request - Paula") is TicketType.UNKNOWN
