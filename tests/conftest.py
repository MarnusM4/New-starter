"""Shared test setup: never reach real Microsoft tenants when identifying clients."""

import pytest

from lib import config


@pytest.fixture(autouse=True)
def offline_domain_discovery():
    """Default every test to 'no tenant domains'; tests that need domains inject a fetcher."""
    config.set_domain_fetcher(lambda cfg: [])
    yield
    config.set_domain_fetcher(config.graph_verified_domains)
