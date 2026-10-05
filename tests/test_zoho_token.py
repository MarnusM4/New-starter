"""tools/zoho_token.py: code exchange + org listing, with the HTTP layer faked."""

import pytest

from tools import zoho_token


class Resp:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        return None

    def json(self):
        return self._data


@pytest.fixture
def zoho(monkeypatch, tmp_path):
    """Fake Zoho endpoints; point the tool at a temp folder so the real .env is never touched."""
    seen = {}

    def fake_post(url, params=None, timeout=None):
        seen["post"] = (url, params)
        return Resp({"access_token": "acc", "refresh_token": "1000.refreshtokenvalue1234"})

    def fake_get(url, headers=None, timeout=None):
        seen["get"] = (url, headers)
        return Resp({"data": [{"id": "6000123", "companyName": "Flawless IT"}]})

    monkeypatch.setattr(zoho_token.requests, "post", fake_post)
    monkeypatch.setattr(zoho_token.requests, "get", fake_get)
    monkeypatch.setattr(zoho_token, "ROOT", tmp_path)
    monkeypatch.setenv("ZOHO_CLIENT_ID", "1000.cid")
    monkeypatch.setenv("ZOHO_CLIENT_SECRET", "csecret-value")
    return seen


def test_saves_to_env_and_hides_secrets(zoho, tmp_path, capsys):
    env = tmp_path / ".env"
    env.write_text(
        "# Zoho\n"
        "ZOHO_CLIENT_ID=PLACEHOLDER_ZOHO_CLIENT_ID\n"
        "ZOHO_REFRESH_TOKEN=PLACEHOLDER_REFRESH_TOKEN\n"
        "# ZOHO_ORG_ID=commented-example\n"
        "AZURE_TENANT_ID=keep-me\n"
    )
    assert zoho_token.main(["--region", "eu", "--code", "1000.abc"]) == 0

    url, params = zoho["post"]
    assert url == "https://accounts.zoho.eu/oauth/v2/token"
    assert params == {"grant_type": "authorization_code", "client_id": "1000.cid",
                      "client_secret": "csecret-value", "code": "1000.abc"}
    assert zoho["get"] == ("https://desk.zoho.eu/api/v1/organizations",
                           {"Authorization": "Zoho-oauthtoken acc"})

    saved = env.read_text().splitlines()
    assert "ZOHO_REFRESH_TOKEN=1000.refreshtokenvalue1234" in saved
    assert "ZOHO_CLIENT_ID=1000.cid" in saved
    assert "ZOHO_CLIENT_SECRET=csecret-value" in saved
    assert "ZOHO_ORG_ID=6000123" in saved
    assert "ZOHO_DESK_BASE_URL=https://desk.zoho.eu" in saved
    assert "AZURE_TENANT_ID=keep-me" in saved                 # other settings untouched
    assert "# ZOHO_ORG_ID=commented-example" in saved         # comments untouched
    assert sum(line.startswith("ZOHO_REFRESH_TOKEN=") for line in saved) == 1

    out = capsys.readouterr().out
    assert "refreshtokenvalue1234" not in out and "csecret-value" not in out
    assert "ZOHO_REFRESH_TOKEN=1000.refr…1234" in out
    assert "ZOHO_ORG_ID=6000123" in out


def test_print_mode_prints_and_writes_nothing(zoho, tmp_path, capsys):
    assert zoho_token.main(["--code", "1000.abc", "--print"]) == 0
    assert not (tmp_path / ".env").exists()
    assert "ZOHO_REFRESH_TOKEN=1000.refreshtokenvalue1234" in capsys.readouterr().out


def test_expired_code_gives_clear_message(monkeypatch):
    monkeypatch.setattr(zoho_token.requests, "post",
                        lambda *a, **k: Resp({"error": "invalid_code"}))
    with pytest.raises(SystemExit, match="Codes expire within minutes"):
        zoho_token.exchange_code("com", "cid", "sec", "old")
