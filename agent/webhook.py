"""Webhook signature verification for the HALO front door.

HALO is configured to sign each webhook with a shared secret (HMAC-SHA256 over the raw
body). We verify before doing ANY work so untrusted callers can't trigger provisioning.

PLACEHOLDER: confirm exactly how HALO signs its webhooks (header name + algorithm) once
you set up the HALO Workflow. The HMAC scheme below is a sensible default; adjust to match.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import sys
import pathlib
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from lib.secrets import get_secret  # noqa: E402

SIGNATURE_HEADER = "X-Halo-Signature"  # TODO: confirm real header name
TIMESTAMP_HEADER = "X-Halo-Timestamp"  # TODO: confirm real header name (if HALO sends one)


def _within_skew(timestamp: str | None) -> bool:
    """Optional replay window. Disabled unless HALO_WEBHOOK_MAX_SKEW (seconds) is set.

    When enabled, a request is only accepted if it carries a timestamp within the skew of
    now — so a captured-and-replayed delivery is rejected once it ages out. Fails closed:
    if enabled but no/invalid timestamp is supplied, the request is refused.
    """
    try:
        max_skew = int(os.environ.get("HALO_WEBHOOK_MAX_SKEW", "0") or 0)
    except ValueError:
        max_skew = 0
    if max_skew <= 0:
        return True  # feature off — no replay window enforced
    if not timestamp:
        return False
    try:
        ts = float(timestamp)
    except ValueError:
        return False
    return abs(time.time() - ts) <= max_skew


def verify_signature(
    raw_body: bytes,
    provided_signature: str | None,
    timestamp: str | None = None,
) -> bool:
    # Resolve via the same path as every other secret (env, then Key Vault) so the webhook
    # secret can live in Key Vault rather than as a plaintext app setting.
    secret = get_secret("HALO_WEBHOOK_SECRET", required=False)
    if not secret or secret.startswith("PLACEHOLDER"):
        # No real secret configured yet. Refuse rather than accept-all.
        return False
    if not provided_signature:
        return False
    if not _within_skew(timestamp):
        return False
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, provided_signature.strip())


def extract_ticket_id(payload: dict) -> str | None:
    """Pull the ticket id out of the webhook body.

    TODO: confirm the real field name HALO sends.
    """
    for key in ("ticket_id", "id", "ticketId"):
        if key in payload:
            return str(payload[key])
    return None
