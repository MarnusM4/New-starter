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


def test_exchange_and_list_orgs(monkeypatch, capsys):
    seen = {}

    def fake_post(url, params=None, timeout=None):
        seen["post"] = (url, params)
        return Resp({"access_token": "acc", "refresh_token": "ref-123"})

    def fake_get(url, headers=None, timeout=None):
        seen["get"] = (url, headers)
        return Resp({"data": [{"id": "6000123", "companyName": "Flawless IT"}]})

    monkeypatch.setattr(zoho_token.requests, "post", fake_post)
    monkeypatch.setattr(zoho_token.requests, "get", fake_get)
    monkeypatch.setenv("ZOHO_CLIENT_ID", "cid")
    monkeypatch.setenv("ZOHO_CLIENT_SECRET", "csecret")

    assert zoho_token.main(["--region", "eu", "--code", "1000.abc"]) == 0

    url, params = seen["post"]
    assert url == "https://accounts.zoho.eu/oauth/v2/token"
    assert params == {"grant_type": "authorization_code", "client_id": "cid",
                      "client_secret": "csecret", "code": "1000.abc"}
    assert seen["get"] == ("https://desk.zoho.eu/api/v1/organizations",
                           {"Authorization": "Zoho-oauthtoken acc"})
    out = capsys.readouterr().out
    assert "ZOHO_REFRESH_TOKEN=ref-123" in out
    assert "ZOHO_ORG_ID=6000123" in out
    assert "ZOHO_DESK_BASE_URL=https://desk.zoho.eu" in out
    assert "csecret" not in out


def test_expired_code_gives_clear_message(monkeypatch):
    monkeypatch.setattr(zoho_token.requests, "post",
                        lambda *a, **k: Resp({"error": "invalid_code"}))
    with pytest.raises(SystemExit, match="Codes expire within minutes"):
        zoho_token.exchange_code("com", "cid", "sec", "old")
