"""Operator alerting for outcomes that need a human (failed / needs-attention).

Posts a short message to an incoming webhook (e.g. a Microsoft Teams or Slack channel) if
NOTIFY_WEBHOOK_URL is configured; otherwise it just logs. Best-effort: a failure to alert
must never break ticket processing.
"""

from __future__ import annotations

import os

import requests


def notify(message: str) -> None:
    url = os.environ.get("NOTIFY_WEBHOOK_URL", "")
    if not url or url.startswith("PLACEHOLDER"):
        print(f"[NOTIFY] {message}")
        return
    try:
        requests.post(url, json={"text": message}, timeout=10).raise_for_status()
    except Exception as exc:  # noqa: BLE001 - alerting must never break processing
        print(f"[NOTIFY] failed to send alert ({exc}): {message}")
