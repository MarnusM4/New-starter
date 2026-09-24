"""Teams alerting via a Workflows webhook (Adaptive Card). No network: requests.post is faked."""

import pytest
import requests

from lib import notify as notify_mod
from lib.notify import build_card, notify


class Recorder:
    def __init__(self, fail=None):
        self.calls = []
        self.fail = fail

    def __call__(self, url, json=None, timeout=None):
        self.calls.append((url, json))
        if self.fail:
            raise self.fail

        class Resp:
            def raise_for_status(self):
                return None

        return Resp()


@pytest.fixture
def post(monkeypatch):
    rec = Recorder()
    monkeypatch.setattr(notify_mod.requests, "post", rec)
    return rec


def _card(payload):
    (attachment,) = payload["attachments"]
    assert payload["type"] == "message"
    assert attachment["contentType"] == "application/vnd.microsoft.card.adaptive"
    return attachment["content"]


def test_not_configured_logs_only(monkeypatch, post, capsys):
    monkeypatch.delenv("TEAMS_WEBHOOK_URL", raising=False)
    notify("Ticket 1: needs attention.", ticket_id="1")
    assert post.calls == []
    assert "needs attention" in capsys.readouterr().out


def test_posts_adaptive_card_with_ticket_and_link(monkeypatch, post):
    monkeypatch.setenv("TEAMS_WEBHOOK_URL", "https://example.test/workflows/hook?sig=abc")
    monkeypatch.setenv(
        "ZOHO_DESK_TICKET_URL", "https://desk.zoho.com/agent/flawless/it/tickets/details/{ticket_id}"
    )
    notify("Ticket 42: client not identified — needs attention.", ticket_id="42")

    (url, payload), = post.calls
    assert url == "https://example.test/workflows/hook?sig=abc"
    card = _card(payload)
    texts = [b.get("text") for b in card["body"] if b["type"] == "TextBlock"]
    assert "Ticket 42: client not identified — needs attention." in texts
    facts = [b for b in card["body"] if b["type"] == "FactSet"][0]["facts"]
    assert facts == [{"title": "Ticket", "value": "42"}]
    assert card["actions"] == [{
        "type": "Action.OpenUrl",
        "title": "Open ticket",
        "url": "https://desk.zoho.com/agent/flawless/it/tickets/details/42",
    }]


def test_no_link_button_without_url_template(monkeypatch):
    monkeypatch.delenv("ZOHO_DESK_TICKET_URL", raising=False)
    assert "actions" not in _card(build_card("msg", ticket_id="42"))


def test_placeholder_url_is_treated_as_unset(monkeypatch, post):
    monkeypatch.setenv("TEAMS_WEBHOOK_URL", "PLACEHOLDER_TEAMS_WEBHOOK_URL")
    notify("msg", ticket_id="1")
    assert post.calls == []


@pytest.mark.parametrize("error", [requests.ConnectionError("down"), RuntimeError("boom")])
def test_send_failure_never_raises_or_leaks_url(monkeypatch, capsys, error):
    monkeypatch.setenv("TEAMS_WEBHOOK_URL", "https://example.test/hook?sig=SECRET")
    monkeypatch.setattr(notify_mod.requests, "post", Recorder(fail=error))
    notify("msg", ticket_id="1")  # must not raise
    out = capsys.readouterr().out
    assert "failed to send Teams alert" in out
    assert "SECRET" not in out
