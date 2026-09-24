"""Operator alerting for outcomes that need a human (failed / needs-attention).

Posts an Adaptive Card to a Microsoft Teams channel through a **Teams Workflows webhook**
("Post to a channel when a webhook request is received"). The older Office 365 connector
incoming webhooks were retired by Microsoft in May 2026, so the plain `{"text": ...}` format
no longer applies.

The webhook URL carries a signature, so it is resolved like any other secret
(TEAMS_WEBHOOK_URL: app setting or Key Vault). If ZOHO_DESK_TICKET_URL is set (a template
containing `{ticket_id}`), the card gets an "Open ticket" button.

Best-effort: not configured -> log only; a failure to alert is logged and never breaks ticket
processing.
"""

from __future__ import annotations

import os
from typing import Any

import requests

from .secrets import get_secret

CARD_TITLE = "Starter/Leaver agent — needs attention"


def ticket_url(ticket_id: str | None) -> str | None:
    """Desk ticket link from the ZOHO_DESK_TICKET_URL template, or None if unset."""
    template = os.environ.get("ZOHO_DESK_TICKET_URL", "")
    if not ticket_id or not template or "{ticket_id}" not in template:
        return None
    return template.replace("{ticket_id}", str(ticket_id))


def build_card(message: str, ticket_id: str | None = None) -> dict[str, Any]:
    """The Workflows webhook payload: one Adaptive Card attachment."""
    body: list[dict[str, Any]] = [
        {"type": "TextBlock", "text": CARD_TITLE, "weight": "Bolder", "size": "Medium",
         "wrap": True},
        {"type": "TextBlock", "text": message, "wrap": True},
    ]
    if ticket_id:
        body.append({"type": "FactSet", "facts": [{"title": "Ticket", "value": str(ticket_id)}]})

    card: dict[str, Any] = {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.4",
        "body": body,
    }
    link = ticket_url(ticket_id)
    if link:
        card["actions"] = [{"type": "Action.OpenUrl", "title": "Open ticket", "url": link}]

    return {
        "type": "message",
        "attachments": [
            {"contentType": "application/vnd.microsoft.card.adaptive", "content": card}
        ],
    }


def notify(message: str, *, ticket_id: str | None = None) -> None:
    try:
        url = get_secret("TEAMS_WEBHOOK_URL", required=False)
    except Exception as exc:  # noqa: BLE001 - e.g. Key Vault unreachable; alerting is best-effort
        print(f"[NOTIFY] couldn't read TEAMS_WEBHOOK_URL ({exc}): {message}")
        return
    if not url:
        print(f"[NOTIFY] {message}")
        return
    try:
        requests.post(url, json=build_card(message, ticket_id), timeout=10).raise_for_status()
    except Exception as exc:  # noqa: BLE001 - alerting must never break processing
        # Log the failure but not the URL (it carries the webhook signature).
        print(f"[NOTIFY] failed to send Teams alert ({type(exc).__name__}): {message}")
