"""Zoho Desk API client (Phase A).

Replaces the earlier HALO PSA client: Zoho Desk is now the ticketing system that drives
starter/leaver provisioning. A Desk ticket (or a Desk workflow rule) fires the webhook;
this client reads the ticket, posts the plan/result back as a comment, and moves the
ticket's status.

PLACEHOLDER: the real custom-field ids, the starter/leaver classifier field, the status
names, and the open-ticket filter are specific to the client's Desk instance and are not
known yet. The methods below have the right SHAPE and are wired into the orchestrator, but
network calls are guarded so nothing breaks before API access exists. Fill in the TODOs
once you have Zoho Desk API credentials and the field mapping.

Auth model (differs from HALO): Zoho uses OAuth2 with a long-lived **refresh token**
(created once via a self-client / authorised grant). At call time we exchange the refresh
token for a short-lived access token against the regional `accounts.zoho.*` endpoint, then
call the regional `desk.zoho.*` API with `Authorization: Zoho-oauthtoken <token>` and the
`orgId` header. Pick the domains for your data-centre region (see ZOHO_*_URL below):
  US  desk.zoho.com     accounts.zoho.com
  EU  desk.zoho.eu      accounts.zoho.eu
  IN  desk.zoho.in      accounts.zoho.in
  AU  desk.zoho.com.au  accounts.zoho.com.au
"""

from __future__ import annotations

import html
import os
import re
import time
from typing import Any

import requests

from .config import ClientConfig, UnknownClientError, identify_client, resolve_config
from .retry import with_retries
from .ticket import StarterDetails, Ticket, TicketType, split_person_name


class ZohoDeskClient:
    def __init__(self) -> None:
        # Pulled from env / Key Vault. See .env.example.
        self.base_url = os.environ.get("ZOHO_DESK_BASE_URL", "https://desk.zoho.com")
        self.accounts_url = os.environ.get("ZOHO_ACCOUNTS_URL", "https://accounts.zoho.com")
        self.org_id = os.environ.get("ZOHO_ORG_ID", "PLACEHOLDER_ORG_ID")
        self.client_id = os.environ.get("ZOHO_CLIENT_ID", "PLACEHOLDER_CLIENT_ID")
        self.client_secret = os.environ.get("ZOHO_CLIENT_SECRET", "PLACEHOLDER_SECRET")
        # Long-lived refresh token minted once for this integration.
        self.refresh_token = os.environ.get("ZOHO_REFRESH_TOKEN", "PLACEHOLDER_REFRESH_TOKEN")
        self._token: str | None = None
        self._token_expiry: float = 0.0

    def _is_placeholder(self) -> bool:
        """No real credentials yet. Keeps dev runs from hitting live/fake endpoints."""
        return self.refresh_token.startswith("PLACEHOLDER") or self.client_secret.startswith(
            "PLACEHOLDER"
        )

    # ------------------------------------------------------------------ auth
    def _get_token(self) -> str:
        """OAuth2 access token via the refresh-token grant.

        Access tokens are short-lived (~1h); cache until shortly before expiry and refresh.
        TODO: confirm the token endpoint path/params for your region if Zoho changes them.
        """
        if self._token and time.time() < self._token_expiry:
            return self._token
        if self._is_placeholder():
            # No real creds yet — fail loudly rather than hitting a fake endpoint.
            raise RuntimeError(
                "Zoho credentials are placeholders; set them in .env / Key Vault"
            )

        resp = requests.post(
            f"{self.accounts_url}/oauth/v2/token",
            params={
                "grant_type": "refresh_token",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "refresh_token": self.refresh_token,
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        self._token = data["access_token"]
        # Refresh a minute early to avoid using a token that expires mid-request.
        self._token_expiry = time.time() + int(data.get("expires_in", 3600)) - 60
        return self._token

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Zoho-oauthtoken {self._get_token()}",
            "orgId": self.org_id,
        }

    # ------------------------------------------------------------------ reads
    def get_ticket_raw(self, ticket_id: str) -> dict[str, Any]:
        """Fetch the raw ticket JSON.

        TODO: confirm whether the starter custom fields come back by default or need
        `?include=` (Desk returns custom fields under the `cf` object).
        """
        def call() -> dict[str, Any]:
            resp = requests.get(
                f"{self.base_url}/api/v1/tickets/{ticket_id}",
                headers=self._headers(),
                timeout=30,
            )
            resp.raise_for_status()
            return resp.json()

        return with_retries(call)

    def list_open_starter_leaver_ticket_ids(self) -> list[str]:
        """Ticket ids of currently-open starter/leaver tickets (for the reconciliation poll).

        TODO: confirm the real filter. Options in Desk: a saved custom View id
        (GET /api/v1/tickets?viewId=...), or GET /api/v1/tickets with a status filter plus a
        category/classification/custom-field filter. Returning open (not yet completed)
        tickets lets the poll re-drive anything the webhook missed; idempotency stops double
        work.
        """
        if self._is_placeholder():
            print("[ZOHO PLACEHOLDER] would list open starter/leaver tickets")
            return []

        def call() -> list[str]:
            resp = requests.get(
                f"{self.base_url}/api/v1/tickets",
                headers=self._headers(),
                params={"status": "Open", "limit": 100},  # TODO: real starter/leaver filter
                timeout=30,
            )
            resp.raise_for_status()
            return [str(t["id"]) for t in resp.json().get("data", [])]

        return with_retries(call)

    def parse_ticket(self, raw: dict[str, Any]) -> Ticket:
        """Map the raw Zoho Desk payload to our normalised Ticket.

        Flawless's onboarding requests come from Zoho Forms: the form emails a
        `${zf:ALL_FIELDS}` summary (a `Label : Value` block) to the helpdesk mailbox, which
        becomes a Desk ticket. So the starter details live in the ticket **description/body**,
        not in structured custom fields. We extract the labelled values (untrusted — only
        whitelisted labels are read, nothing is executed as instructions), work out the
        client from the company name and/or email domains, and build a validated
        StarterDetails.

        Never raises for an unidentified client: client_id is set to a readable marker and
        the orchestrator flags it via resolve_config -> UnknownClientError.
        """
        body = self._ticket_body(raw)

        # Forms differ per client, so identify the client from label-independent clues first,
        # then read that client's label overrides and subject keywords.
        company = _extract_company(body)
        config: ClientConfig | None = None
        try:
            client_id = identify_client(company, body)
            config = resolve_config(client_id)
        except UnknownClientError as exc:
            client_id = _unidentified_marker(company, body, exc)

        labels = dict(DEFAULT_FIELD_LABELS)
        if config is not None:
            labels.update(config.field_labels or {})
        fields = parse_summary(body, labels)

        ticket_type = classify_subject(str(raw.get("subject", "")), config)

        starter = None
        if ticket_type is TicketType.STARTER:
            _prefix, first, last = split_person_name(fields.get("new_starter_name", ""))
            starter = StarterDetails(
                first_name=first,
                last_name=last,
                job_title=fields.get("job_title"),
                department=fields.get("department"),
                role=fields.get("role"),
                manager_email=fields.get("manager_email"),
                # The requested NS email's local part is the intended login/username; the
                # domain comes from the client's upn_suffix config. Full username is still
                # validated against the allow-list downstream (build_username).
                desired_username=_email_local_part(fields.get("ns_email")),
                start_date=fields.get("start_date"),
            )

        return Ticket(
            ticket_id=str(raw.get("id", ticket_id_fallback(raw))),
            client_id=client_id,
            ticket_type=ticket_type,
            starter=starter,
        )

    @staticmethod
    def _ticket_body(raw: dict[str, Any]) -> str:
        """The text we parse the form summary out of.

        Desk's `description` holds the first message. TODO: confirm on a real ticket whether
        the full summary is there or in the latest thread; if needed, fetch
        GET /api/v1/tickets/{id}/latestThread and use its `content`.
        """
        return str(raw.get("description") or raw.get("content") or "")

    # ------------------------------------------------------------------ writes
    def post_note(self, ticket_id: str, note: str) -> None:
        """Append a comment to the ticket (used to post the provisioning plan / results).

        Posts a private (internal) comment by default so plan detail isn't exposed to the
        requester. TODO: confirm you want isPublic=false for your workflow.
        """
        if self._is_placeholder():
            # Dev mode: don't pretend to write. Surface what we'd send.
            print(f"[ZOHO PLACEHOLDER] would post comment to ticket {ticket_id}:\n{note}")
            return

        def call() -> None:
            requests.post(
                f"{self.base_url}/api/v1/tickets/{ticket_id}/comments",
                headers=self._headers(),
                json={"content": note, "isPublic": False},
                timeout=30,
            ).raise_for_status()

        with_retries(call)

    def update_status(self, ticket_id: str, status: str) -> None:
        """Move the ticket to a new status.

        Zoho Desk statuses are **named** strings (unlike HALO's numeric ids). Our logical
        names map to the custom Desk statuses via desk_status_name (STATUS_NAME_MAP defaults,
        ZOHO_STATUS_* overrides).
        """
        desk_status = desk_status_name(status)
        if self._is_placeholder():
            print(f"[ZOHO PLACEHOLDER] would set ticket {ticket_id} status -> {status} ({desk_status})")
            return

        def call() -> None:
            requests.patch(
                f"{self.base_url}/api/v1/tickets/{ticket_id}",
                headers=self._headers(),
                json={"status": desk_status},
                timeout=30,
            ).raise_for_status()

        with_retries(call)


# --------------------------------------------------------------------------- intake parsing
#
# Canonical starter field -> the Flawless form's label text in the ${zf:ALL_FIELDS} summary.
# A client whose form uses different labels overrides these via `field_labels:` in
# clients/<client>.yaml (merged over these defaults). TODO: confirm the exact label strings
# (incl. the manager field, not visible in the sample) against a live ticket.
DEFAULT_FIELD_LABELS: dict[str, str] = {
    "company": "Company's Name",
    "new_starter_name": "New Starter's Name",
    "ns_email": "New Starter's NS Email Address",
    "job_title": "Job Title",
    "department": "Department",
    "country": "Country",
    "start_date": "Start Date",
    "manager_email": "Manager's Email",  # TODO: confirm real label
}


def _html_to_text(s: str) -> str:
    """Best-effort HTML → text so a `Label : Value` block survives on one line per field.

    Desk may store the email body as HTML. Turn row/line boundaries into newlines and cell
    boundaries into a ' : ' separator, drop remaining tags, unescape entities, and collapse
    any doubled separators. Plain-text bodies pass through unchanged.
    """
    if "<" in s and ">" in s:
        s = re.sub(r"(?i)<br\s*/?>", "\n", s)
        s = re.sub(r"(?i)</(tr|p|div|li|h[1-6])\s*>", "\n", s)
        s = re.sub(r"(?i)</td>\s*<td[^>]*>", " : ", s)
        s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s)
    s = re.sub(r"[ \t]*:[ \t]*:[ \t]*", " : ", s)  # collapse a doubled colon from cell joins
    return s


def _extract_one(body: str, label: str) -> str | None:
    """Pull a single `Label : Value` off its own line (case-insensitive). None if absent."""
    flat = _html_to_text(body)
    m = re.search(
        rf"^[ \t]*{re.escape(label)}[ \t]*:[ \t]*(.*\S)[ \t]*$",
        flat,
        re.IGNORECASE | re.MULTILINE,
    )
    return m.group(1).strip() if m else None


def parse_summary(body: str, labels: dict[str, str]) -> dict[str, str]:
    """Extract the whitelisted labelled values from the form-summary body.

    Only the given labels are read; any other content in the (untrusted) body is ignored.
    Returns a dict keyed by canonical field name.
    """
    out: dict[str, str] = {}
    for canon, label in labels.items():
        val = _extract_one(body, label)
        if val:
            out[canon] = val
    return out


# Forms word the company question differently; this is only one clue among several.
COMPANY_LABELS: tuple[str, ...] = ("Company's Name", "Company Name", "Company")


def _extract_company(body: str) -> str | None:
    for label in COMPANY_LABELS:
        value = _extract_one(body, label)
        if value:
            return value
    return None


def _unidentified_marker(company: str | None, body: str, exc: Exception) -> str:
    """A readable client_id for a ticket we couldn't place (shown in the technician note)."""
    from .config import AmbiguousClientError, email_domains_in

    kind = "ambiguous" if isinstance(exc, AmbiguousClientError) else "unidentified"
    domains = ", ".join(email_domains_in(body)[:5]) or "none"
    comp = (company or "none")[:60]
    return f"{kind}: company='{comp}', email domains={domains}"


def _email_local_part(value: str | None) -> str | None:
    """Return the part before '@' of a requested NS email (the intended login), else None.

    e.g. "paulap@naturalselection.travel" -> "paulap". A bare value with no '@' is returned
    as-is; empty/None -> None. The result is still validated against the username allow-list
    downstream, so this only normalises the source, it does not trust it.
    """
    if not value:
        return None
    return value.split("@", 1)[0].strip() or None


# Form titles vary per client ("Onboarding", "New Starter IT Form", "New User", ...). A client
# with other wording adds it via starter_subject_keywords / leaver_subject_keywords.
DEFAULT_STARTER_KEYWORDS: tuple[str, ...] = (
    "onboarding", "on-boarding", "new starter", "new user", "new employee", "new hire", "joiner",
)
DEFAULT_LEAVER_KEYWORDS: tuple[str, ...] = (
    "offboarding", "off-boarding", "leaver", "exit", "termination", "departure",
)


def _mentions(subject: str, keyword: str) -> bool:
    """Whole-word/phrase, case-insensitive; spaces in a keyword also match '-' or runs of space."""
    parts = [re.escape(p) for p in keyword.lower().split()]
    pattern = r"[\s-]+".join(parts)
    return re.search(rf"(?<![a-z0-9]){pattern}(?![a-z0-9])", subject.lower()) is not None


def classify_subject(subject: str, config: ClientConfig | None = None) -> TicketType:
    """STARTER / LEAVER when the subject clearly says so; UNKNOWN when neither or both match.

    UNKNOWN is flagged for a technician — an unclear ticket never creates an account.
    """
    starter_kw = list(DEFAULT_STARTER_KEYWORDS)
    leaver_kw = list(DEFAULT_LEAVER_KEYWORDS)
    if config is not None:
        starter_kw += list(config.starter_subject_keywords or [])
        leaver_kw += list(config.leaver_subject_keywords or [])

    is_starter = any(_mentions(subject, k) for k in starter_kw)
    is_leaver = any(_mentions(subject, k) for k in leaver_kw)
    if is_starter and not is_leaver:
        return TicketType.STARTER
    if is_leaver and not is_starter:
        return TicketType.LEAVER
    return TicketType.UNKNOWN


# Logical status names used by the orchestrator, mapped to the custom ticket statuses you
# create in Zoho Desk (Setup -> Customization -> Ticket statuses). Flagged tickets land in
# "Needs Attention" / "Automation Failed", so a Desk view on those shows everything the agent
# couldn't handle. Rename any of them without a code change via the ZOHO_STATUS_* settings.
STATUS_AWAITING_APPROVAL = "awaiting_approval"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"
STATUS_NEEDS_ATTENTION = "needs_attention"

STATUS_NAME_MAP: dict[str, str] = {
    STATUS_AWAITING_APPROVAL: "Awaiting Approval",
    STATUS_COMPLETED: "Provisioned",
    STATUS_FAILED: "Automation Failed",
    STATUS_NEEDS_ATTENTION: "Needs Attention",
}


def desk_status_name(status: str) -> str:
    """The Desk status name for a logical status: ZOHO_STATUS_<NAME> env override, else default."""
    override = os.environ.get(f"ZOHO_STATUS_{status.upper()}", "").strip()
    return override or STATUS_NAME_MAP.get(status, status)


def ticket_id_fallback(raw: dict[str, Any]) -> str:
    return str(raw.get("ticketNumber", "UNKNOWN"))
