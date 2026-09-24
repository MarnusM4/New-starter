# Roadmap — Starter/Leaver Automation Agent

Phased delivery. Each phase is independently shippable and safe to run against real
tickets at the point it's reached. See [README.md](README.md) for architecture and
[CLAUDE.md](CLAUDE.md) for how the docs fit together.

**Status:** Phase A ✅ · Phase B ✅ · Phase C ✅ · Phase D ✅ — all code complete
(awaiting real Zoho Desk/Azure credentials to run live) · Phase E not started.

---

## Phase A — Webhook front door + read & decide (no writes) ✅

Stand up the trigger and the read/decision core. **No accounts are created in this phase**,
so it is safe to point at real tickets.

- Signature-verified **Azure Function** that receives the Zoho Desk workflow webhook and invokes
  the per-ticket core.
- Zoho Desk API client + OAuth2 (refresh-token grant) auth.
- Fetch the triggering ticket and its user-info table.
- Client resolver → load `clients/<client-id>.yaml`; config loader + schema validation.
- Produce a structured "provisioning plan" and post it as a Zoho Desk comment.
- Idempotent handling of retries / duplicate webhook deliveries.

**Done when:** a test webhook posts a correct provisioning-plan note with zero writes to any
identity system; unsigned/invalid webhooks are rejected; duplicate deliveries process once.

---

## Phase B — Provisioning, both paths (constrained layer) ✅ (code complete)

Build both action implementations behind a common interface, with a **human approval gate**
before any write. `identity_path` in the client config selects the path per ticket.

> Implemented: approval gate + dispatcher (`agent/provision.py`), Entra path via Graph REST
> (`actions/entra/action.py`, `lib/graph.py`), local-AD path via Azure Automation REST
> (`actions/local_ad/action.py`, `lib/azure_automation.py`). All network calls are guarded
> against placeholder credentials and unit-tested with injected fake transports. **Live
> end-to-end runs are pending real Zoho Desk + Azure credentials.**

- `/actions/entra` — Microsoft Graph: create user, assign license, add to default/role
  groups. Tested against a sandbox tenant.
- `/actions/local_ad` — Azure Automation account + **Hybrid Runbook Worker** on a
  domain-joined member server in the client network; PowerShell runbooks
  (`ActiveDirectory` module) for user creation + group adds; triggered via the Azure REST
  API with validated params only. Tested in a lab domain; AD Connect sync verified.

**Done when:** both paths create the correct user + license + groups end-to-end; an
unapproved run does nothing; malformed/malicious ticket fields are rejected, not executed.

---

## Phase C — Write-back & audit ✅ (code complete)

- Update the Zoho Desk ticket (note + status) with exactly what was done.
- Structured audit log of every action, tied to the ticket ID.

> Implemented: `ZohoDeskClient.update_status` + logical status names → Desk status-name map
> (placeholder ids). Every orchestrator outcome now writes back a note **and** a status —
> awaiting approval, completed, failed, or needs-attention (unknown client). Provisioning
> is wrapped so failures post a note, set FAILED, audit the error, and re-raise. Each run
> gets a correlation `run_id` threaded through its audit events. The client is identified
> from the form summary's email domains (auto-discovered from each client's Microsoft tenant)
> and/or its "Company's Name" answer (`clients/_lookup.yaml` aliases); unidentified or
> ambiguous clients are flagged for a human, never guessed. Starter vs leaver comes from the
> subject keywords; an unclear subject is flagged too.

**Done when:** every run produces a complete, accurate audit record and a clear ticket
write-back. _(Status-id values are placeholders until the real Zoho Desk instance is wired up.)_

---

## Phase D — Reconciliation poll (safety net) ✅ (code complete)

- Lightweight scheduled job that catches any starter/leaver tickets the webhook
  missed/failed, invoking the same Phase A–C core.

> Implemented: `reconcile_poll` timer trigger (every 15 min) → `agent/reconcile.py` lists
> open starter/leaver tickets and feeds each through `process_ticket`; one failing ticket
> is caught/audited and doesn't abort the batch. **Idempotency made durable**: the
> in-memory guards were replaced by a pluggable `StateStore` (`lib/state.py`) so the
> webhook Function and the timer Function share state and survive restarts — `FileState`
> for dev, Azure Table recommended for prod.

**Done when:** a skipped webhook delivery is picked up by the poll with the same result and
no double-processing. _(Verified by tests; live verification pending credentials.)_

---

## Phase E — Leaver process

- Reuse the skeleton across both identity paths: disable account, remove licenses/groups,
  convert mailbox, etc., per client config.

**Done when:** a leaver ticket fully deprovisions on both Entra and local-AD clients per
their config, with the same approval gate and audit trail.

---

## Hardening — done in code

A hardening pass landed alongside Phases B–D. Done now:

- **Idempotent Entra steps** — `create_user` reuses an existing user, `assign_license` skips
  already-assigned SKUs, `add_groups` skips existing memberships. Safe to re-run after a
  partial failure (`actions/entra/action.py`).
- **Retry/backoff** on all transports — 429/5xx retried with exponential backoff +
  Retry-After; 4xx fails fast (`lib/retry.py`, applied in Zoho Desk/Graph/Automation).
- **Azure Table state store** — `AzureTableState` implemented; `default_state()` auto-selects
  it when `STATE_TABLE_CONNECTION_STRING` is set, else `FileState` (`lib/state.py`).
- **Key Vault secret resolution** — `get_secret` falls back to Key Vault when
  `KEY_VAULT_URL` is set (`lib/secrets.py`).
- **Operator alerting** — failed / unknown-client outcomes call `notify()`
  (Teams Workflows webhook via `TEAMS_WEBHOOK_URL`, Adaptive Card with an "Open ticket"
  button) (`lib/notify.py`).
- **Client schema** — added `upn_suffix` and `username_format`.
- **Pinned dependency ranges** (`requirements.txt`).

## Hosting & operations

**Decision: hosted in Conosco's own Azure tenant/subscription** (not per-client tenants) —
central control, one Key Vault, one audit trail, one deployment to monitor. Full detail
(components, the Azure Function App, 24/7 plan choices, on-prem Hybrid Worker, deployment)
is in the **Hosting & operations** section of [README.md](README.md).

Provisioning the Azure environment is **deferred infrastructure work** (needs the Azure
subscription + access):

1. Create the resource group in Conosco's subscription with: Function App, Storage Account
   (state), Key Vault, Application Insights, and an Automation account (for local-AD).
2. Choose the Functions plan — Consumption (cheapest) vs Premium/Flex (no cold start, VNet).
3. Give the Function App a Managed Identity with access to Key Vault + Automation.
4. Set up deployment (`func azure functionapp publish` or CI/CD).
5. Install a Hybrid Runbook Worker per local-AD client (covered above).

## Deferred / hardening — bookmarked (need live credentials or infra)

These are written but **cannot be verified without real access**; revisit when provisioning
real tenants:

1. **Live-test Azure Table state** against a real storage account (class is ready, untested
   live).
2. **Live-test Key Vault** resolution against a real vault + managed identity (code ready).
3. **Per-client least-privilege app registrations** — create scoped Graph apps per tenant
   and store their secrets in Key Vault; no shared credential.
4. **Lock down the approval signal in Zoho Desk** — confirm the real "approved/approved_by"
   fields and restrict who can set them; `is_approved` / `approver` currently use
   placeholder fields.
5. **Real Zoho Desk field labels + status names** — confirm each client form's labels
   (`DEFAULT_FIELD_LABELS` / per-client `field_labels`), any subject wording outside the
   default keywords, and create the Desk statuses named in `STATUS_NAME_MAP` (or override via `ZOHO_STATUS_*`).
   Grant `Domain.Read.All` in each client tenant so client domains are discovered.
6. **Create the Teams Workflows webhook + Desk statuses** — set `TEAMS_WEBHOOK_URL` and
   `ZOHO_DESK_TICKET_URL`, create the four custom statuses in Desk, and test a flagged ticket.
7. **Local-AD post-sync licensing** — after AD Connect sync, apply Entra licensing/cloud
   groups for `local_ad` clients (currently noted as pending-sync only).
