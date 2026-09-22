"""Webhook authentication for the Zoho Desk front door.

Unlike HALO, Zoho Desk workflow/webhook rules do not HMAC-sign the request body with a
shared secret. Instead we secure the front door with a **shared secret token** that the Desk
workflow is configured to send on every delivery (in a custom header, or as a query-string
parameter on the webhook URL). We verify it before doing ANY work, so untrusted callers
can't trigger provisioning. This is layered on top of the Azure Functions function key, so
the endpoint requires both.

If you configure a Desk webhook variant that DOES sign the payload, switch verify_token for
an HMAC check (see git history for the previous HMAC implementation).

PLACEHOLDER: confirm the header name / query param you set on the Desk workflow, then set
ZOHO_WEBHOOK_SECRET in .env / Key Vault to match.
"""

from __future__ import annotations

import hmac
import os
import sys
import pathlib
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from lib.secrets import get_secret  # noqa: E402

# Header the Desk workflow is configured to send the shared secret in.
SIGNATURE_HEADER = "X-Zoho-Webhook-Token"  # TODO: confirm the header name you configure
TIMESTAMP_HEADER = "X-Zoho-Webhook-Timestamp"  # optional; only if you send one for replay defence


def _within_skew(timestamp: str | None) -> bool:
    """Optional replay window. Disabled unless ZOHO_WEBHOOK_MAX_SKEW (seconds) is set.

    When enabled, a request is only accepted if it carries a timestamp within the skew of
    now — so a captured-and-replayed delivery is rejected once it ages out. Fails closed:
    if enabled but no/invalid timestamp is supplied, the request is refused.
    """
    try:
        max_skew = int(os.environ.get("ZOHO_WEBHOOK_MAX_SKEW", "0") or 0)
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
    raw_body: bytes,  # kept in the signature for a drop-in swap back to HMAC if needed
    provided_token: str | None,
    timestamp: str | None = None,
) -> bool:
    """Constant-time compare of the shared secret token the Desk workflow sends.

    Named verify_signature so function_app.py stays unchanged across the HALO→Zoho swap.
    """
    # Resolve via the same path as every other secret (env, then Key Vault).
    secret = get_secret("ZOHO_WEBHOOK_SECRET", required=False)
    if not secret or secret.startswith("PLACEHOLDER"):
        # No real secret configured yet. Refuse rather than accept-all.
        return False
    if not provided_token:
        return False
    if not _within_skew(timestamp):
        return False
    return hmac.compare_digest(secret.encode(), provided_token.strip().encode())


def extract_ticket_id(payload: dict) -> str | None:
    """Pull the ticket id out of the webhook body.

    Desk workflow payloads are configurable; include the ticket id in the webhook body and
    confirm the field name here. TODO: confirm the real field name your Desk workflow sends.
    """
    for key in ("id", "ticketId", "ticket_id", "ticketNumber"):
        if key in payload:
            return str(payload[key])
    return None
