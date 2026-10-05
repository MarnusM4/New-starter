# Starter / Leaver Automation Agent

An agent that automates **starter** (and later **leaver**) account provisioning for an
MSP's clients, driven by tickets logged in the **Zoho Desk** ticketing system.

When a client logs a starter ticket, the agent reads the new-user details, loads that
client's process, provisions the account on the correct identity platform, assigns the
license, applies group/permission templates, and writes the result back to the Zoho Desk ticket —
removing repetitive manual provisioning while staying **safe and auditable**.

> See [ROADMAP.md](ROADMAP.md) for the phased delivery plan and [CLAUDE.md](CLAUDE.md) for
> agent/contributor working notes.

---

## How it works

```
Zoho Form (client onboarding) ──emails ${zf:ALL_FIELDS} summary──► helpdesk mailbox
   │                                                                     │
   ▼                                                          becomes a Zoho Desk ticket
Zoho Desk ticket (Starter)
   │  Zoho Desk workflow → webhook → token-verified Azure Function front door
   ▼
Orchestrator / Agent  ── reads the form summary from the ticket body (Zoho Desk API)
   │                  ── identifies client (email domains / company name) → loads clients/<client>.yaml
   │                  ── classifies starter / leaver from the subject (unclear → technician)
   │                  ── validates ticket data (treat as untrusted)
   │                  ── HUMAN APPROVAL GATE (privileged action)
   ▼
Constrained action layer (holds the privileged credentials)
   ├─ Azure/Entra path  → Microsoft Graph: create user, assignLicense, group add
   └─ Local-AD path     → Azure Automation Hybrid Worker runbook (PowerShell AD module)
                          → Azure AD Connect syncs user up to Entra
   ▼
Write result back to Zoho Desk ticket (note + status)  +  append to audit log
```

### Intake — Zoho Forms → email summary → Zoho Desk ticket

Onboarding requests originate from a **Zoho Form** (one per client). On submit, Zoho Forms
emails a `${zf:ALL_FIELDS}` **form summary** — a clean `Label : Value` block — to the
helpdesk mailbox, which becomes a **Zoho Desk ticket**. The starter details therefore live in
the ticket **body/description**, not in structured custom fields. The agent parses that
labelled block ([lib/zoho.py](lib/zoho.py) `parse_summary` + `DEFAULT_FIELD_LABELS`), treating
the body as **untrusted** — only whitelisted labels are read. A digital PDF of the form is
also attached, but the email summary is the source of truth (no PDF parsing / OCR).

### Trigger — Zoho Desk webhook

A Zoho Desk workflow fires a webhook on starter/leaver tickets to a token-verified **Azure
Function** front door, which invokes the per-ticket core in real time. A lightweight
scheduled **reconciliation poll** (`reconcile_poll` timer, every 15 min) is kept as a
safety net to catch missed/failed webhook deliveries — it re-drives open starter/leaver
tickets through the same core. Both the webhook and the poll share a durable **state
store** ([lib/state.py](lib/state.py)) so a ticket is never planned twice or provisioned
twice (`FileState` for dev; back it with Azure Table Storage in production).

### Two identity paths (both supported from the start)

`identity_path` in each client's config selects the route per ticket:

- **Entra (Azure-only):** Microsoft Graph creates the cloud user, assigns the license, and
  adds groups directly.
- **Local AD (synced to Azure):** Graph **cannot** write on-prem AD, so an **Azure
  Automation Hybrid Runbook Worker** — Microsoft software on a domain-joined member server
  in the client's network — runs a PowerShell runbook locally to create the AD user. Azure
  AD Connect then syncs the user up to Entra. The agent never runs on the client server; it
  only triggers the runbook with validated parameters.

---

## Per-client configuration

Each client's process is defined in a **version-controlled** file: `clients/<client-id>.yaml`.

```yaml
client_id: acme
identity_path: entra        # entra | local_ad
tenant_id: <guid>           # for entra path
license_skus:               # Graph SKU part numbers / ids
  - O365_BUSINESS_PREMIUM
default_groups:
  - All-Staff
  - VPN-Users
role_group_map:             # optional: map ticket "role" field → extra groups
  Sales: [CRM-Users, Sales-Shared]
usage_location: GB
approval_required: true
field_labels:               # optional: override intake form labels for this client
  job_title: "Position"     # only override labels that differ from the Flawless defaults
```

For the `local_ad` path the file also carries `automation_account`, `hybrid_worker_group`,
`subscription_id`, `resource_group`, `runbook_name`, and `ou_path`.

`clients/_schema.py` defines the shape so a malformed client file fails fast.

**Form labels.** Each client's form words its questions differently ("New Starter's Name"
vs "New Users Name & Surname"), so every agent field accepts several wordings
([lib/zoho.py](lib/zoho.py) `DEFAULT_FIELD_LABELS`), matched ignoring case, apostrophes,
"&"/"and" and a trailing "?". Most clients need nothing. For an unusual wording, add it to
the client's optional `field_labels` (one label or a list; tried before the defaults) — or,
if other clients are likely to use it too, add it to `DEFAULT_FIELD_LABELS`.

**Names.** A Zoho Name field ("Ms., Paula, Potgieter") is split on commas; a free-text
"Name & Surname" box takes the first word as the first name and **the rest as the surname**,
so "Marnus van den Heever" → Marnus / van den Heever. A leading title (Mr, Ms, Dr, …) is
dropped. The username comes from the new user's email address when the form gives one.

### Mapping a client to its config

Every client's onboarding form emails the **same** helpdesk mailbox, and each client's form
asks different questions, so the ticket doesn't say which client it's for. The agent combines
clues from the form summary (`lib/config.py` `identify_client`):

- **Email domains** — every email address in the summary (requester, new starter, ...),
  regardless of which question it answers. Each client's domains are **discovered
  automatically** from its Microsoft tenant (verified domains via Graph `GET /domains`, cached
  for 6h), so a client with several domains needs nothing listed, and a newly added domain is
  picked up on the next refresh. Domains owned by no client (e.g. Flawless's own helpdesk
  address in the email text) are ignored.
- **Company's Name** — when a client's form has that question, mapped via the optional
  aliases in `clients/_lookup.yaml` (case-insensitive).

The clues must all point at **one** client. No match, or clues pointing at different clients
(including a domain that shows up in two tenants), flags the ticket for a human (note +
needs-attention status) — never guessed. Text typed on a form is never used as a file path:
only known config file names are accepted.

**Onboarding a new client** is creating their `clients/<client>.yaml` (tenant, identity path,
licences, groups) — needed anyway to provision — and granting `Domain.Read.All` in their
tenant. Domain matching then works with no further setup. Optional `email_domains:` in the
client file covers a domain that isn't verified in the tenant.

### Starter vs leaver

Form titles vary per client ("Onboarding", "New Starter IT Form", "New User", ...), so the
ticket **subject** is matched against keyword lists (`lib/zoho.py` `classify_subject`):
starter — onboarding, new starter, new user, new employee, new hire, joiner; leaver —
offboarding, leaver, exit, termination, departure. A client with other wording adds
`starter_subject_keywords` / `leaver_subject_keywords` to its file. A subject that matches
**neither or both** is flagged for a technician; it never creates an account.

**Ordinary support tickets are left alone.** A ticket with no starter/leaver wording in its
subject **and** no form summary in its body (no "New Starter's Name", NS email or start
date) isn't an onboarding request at all: the agent does nothing to it — no comment, no
status change, no alert. Only tickets that are clearly forms but can't be classified get
flagged. **Leaver tickets** are also left alone (audit only) until the leaver process is
built.

The Desk workflow that triggers the agent should only fire for tickets **sent by Zoho
Forms** (filter on the sender address of the form notification emails), not on subject
words alone — e.g. an internal ticket titled "New Starter Form Edits" mentions "new starter"
but isn't a request, and would otherwise be flagged. The rule above is the safety net.

### Flagging & alerts

When the agent can't safely act (client not identified or ambiguous, starter/leaver unclear,
missing or invalid details, self-approval, provisioning failed), it **flags** the ticket and
takes no action in any client tenant:

1. **Internal comment** on the Zoho Desk ticket (private — the requester doesn't see it)
   saying what went wrong.
2. **Ticket status** moves to **"Needs Attention"** (or **"Automation Failed"** when
   provisioning itself failed), so it shows up in a Desk view technicians already watch.
3. **Teams alert** — an Adaptive Card in the ops channel with the reason, ticket number and an
   **Open ticket** button (`lib/notify.py`). Teams pushes it to phones through the Teams app.
4. **Audit entry** tied to the ticket id.

Setup:

- **Zoho Desk** — create five custom ticket statuses (Setup → Customization → Layouts and
  Fields → Ticket Status → pick the department → Add Status):

  | Status | Status type | Set by |
  |---|---|---|
  | Awaiting Approval | On Hold | agent — plan posted, waiting for a technician |
  | Approved | Open | **technician** — the go-ahead; the next run creates the account |
  | Needs Attention | Open | agent — flagged |
  | Automation Failed | Open | agent — provisioning failed |
  | Provisioned | Open | agent — account done (laptop/software tasks remain; close by hand) |

  Different names are fine for the agent's four; set them via `ZOHO_STATUS_AWAITING_APPROVAL`
  / `_COMPLETED` / `_FAILED` / `_NEEDS_ATTENTION`. "Approved" must be named exactly that.
  Add a Desk view filtered on *Needs Attention* + *Automation Failed*.
- **Teams** — in the target channel: **Workflows → "Post to a channel when a webhook request
  is received"**, then copy the webhook URL into `TEAMS_WEBHOOK_URL` (Key Vault in production —
  the URL carries a signature). Microsoft retired the older Office 365 "Incoming Webhook"
  connectors in May 2026, so a Workflows webhook is required.
- **Ticket link** — set `ZOHO_DESK_TICKET_URL` to your Desk ticket URL pattern with
  `{ticket_id}` in place of the number (copy any ticket's URL from the browser) to get the
  **Open ticket** button.

If `TEAMS_WEBHOOK_URL` isn't set the alert is only logged; a failed alert never stops ticket
processing.

---

## APIs & permissions

| System | Use | Auth / permissions |
|---|---|---|
| **Zoho Desk API** | Read ticket body (form summary), post comment, update status | OAuth2 refresh-token grant; one scoped Zoho Desk self-client application |
| **Microsoft Graph** | Entra path: create user, `assignLicense`, group add | App registration **per client tenant** (or multi-tenant, consented per tenant); least-privilege app permissions, e.g. `User.ReadWrite.All`, `Group.ReadWrite.All`, `Organization.Read.All`, `Domain.Read.All` (client identification) |
| **Azure Automation** | Local-AD path: trigger runbook on Hybrid Worker | Azure REST API; runbook + Hybrid Runbook Worker per local-AD client |
| **On-prem AD** | `New-ADUser`, group membership (via runbook) | PowerShell `ActiveDirectory` module on the Hybrid Worker; credentials scoped per client |

Privileged credentials are held by the **constrained action layer**, never by the agent.

---

## Security

- **Least privilege per client** — separate scoped credentials per tenant, no shared
  god-credential.
- **Secrets in a vault** (Azure Key Vault) / environment — never in the repo or agent prompt.
- **Human approval gate with separation of duties** before any account/license creation —
  an approval whose approver is also the requester is rejected and flagged, not actioned.
- **Ticket content is untrusted data, not instructions** — only specific validated fields
  drive actions (prompt-injection defence). Ticket-derived identity fields are validated at
  the trust boundary: required fields must be present, and the username must pass a strict
  allow-list (`lib/ticket.py`) before it can reach account creation.
- **No silent account takeover** — provisioning refuses to attach licenses/groups to a
  pre-existing account it didn't create for this ticket (`UserCollisionError`); reuse is
  only allowed for a genuine safe re-run of the same ticket.
- **Constrained action layer** holds privileged rights; the agent passes structured params
  validated against client config.
- **Full audit trail** tying every action to a ticket ID (with a per-run `run_id`) plus the
  approver; idempotency / duplicate guard.
- **Atomic idempotency** — the provisioned marker is claimed with a compare-and-set
  (insert-if-absent) before any privileged write, so a concurrent webhook + reconciliation
  poll (or a duplicate/replayed delivery) can't double-provision; a failed attempt releases
  the claim so the poll can retry.
- **Webhook front door:** Azure function key **plus** a shared-secret token the Desk
  workflow sends, verified in constant time before any work (`agent/webhook.py`),
  fail-closed on a missing/placeholder secret. The secret resolves via Key Vault like every
  other secret. Optional replay window (`ZOHO_WEBHOOK_MAX_SKEW`) rejects stale deliveries.
- **Retry/backoff** on all REST calls (429/5xx); **alerting** (`lib/notify.py`) on
  failed / needs-attention outcomes. Client-visible notes and external alerts carry a
  correlation `run_id` rather than raw internal error text.
- **Secrets from env or Key Vault** ([lib/secrets.py](lib/secrets.py)); placeholder values
  are refused so nothing fires with fake credentials.
- **Outbound-only** Hybrid Worker connectivity (HTTPS 443) — no inbound firewall holes.

---

## Hosting & operations

**Decision: the system is hosted in Conosco's own Azure tenant/subscription** (not in each
client's tenant). This gives central control, one Key Vault, one audit trail, and one place
to deploy and monitor. It reaches into each client's Microsoft Entra tenant using
per-client app credentials, and into local-AD clients via a Hybrid Runbook Worker.

### What actually runs, and where

Everything except the on-prem worker is managed Azure PaaS — there is **no VM/server to
patch** and nothing "running under a desk". All of it lives in a single resource group in
Conosco's subscription:

| Component | Role | Always-on |
|---|---|---|
| **Azure Function App** (`function_app.py`) | Core: `zoho_webhook` (HTTP trigger) + `reconcile_poll` (timer) | Yes — serverless, Microsoft-managed |
| **Azure Key Vault** | Holds Zoho Desk + Microsoft credentials | Yes |
| **Azure Storage / Table** | Durable idempotency state + Functions runtime | Yes |
| **Application Insights** | Logging, monitoring, alerting | Yes |
| **Azure Automation account** | Triggers runbooks on Hybrid Workers (local-AD path) | Yes |
| **Hybrid Runbook Worker** | *Only for local-AD clients* — runs PowerShell to create on-prem AD accounts | Must stay powered on (in the client's network) |
| **Zoho Desk** (PSA) | Sends the trigger webhook; receives write-back | Already hosted |
| **Microsoft Entra / Graph** | Where cloud accounts are created | Microsoft cloud |

```
            (Microsoft Azure — Conosco's tenant, 24/7)
Zoho Desk ─webhook─► Azure Function App ──► Entra / Graph (cloud accounts)
  ▲                  │   │
  └──writes back─────┘   └──► local-AD clients: Azure Automation ──► Hybrid Worker
                                                  (in client network) ──► on-prem AD
        backed by:  Key Vault · Table Storage · Application Insights
```

### The Azure Function App in detail

The "Azure app" is an **Azure Function App** — a managed, serverless host for event-driven
code. We deploy `function_app.py` to it; Azure runs our functions on demand in response to
triggers and scales instances automatically. Key facts:

- **Two functions, two triggers.** `zoho_webhook` is an **HTTP trigger** (a public HTTPS
  endpoint Zoho Desk calls). `reconcile_poll` is a **timer trigger** (cron, every 15 min) that
  re-checks open tickets as a safety net.
- **Runtime:** Python (3.11) worker. Dependencies from `requirements.txt`.
- **Stateless by design.** Each invocation is independent; any "have I done this already?"
  state lives in **Table Storage** (`lib/state.py`), which is why duplicate webhooks and
  multiple instances never double-provision.
- **Hosting plan — pick per responsiveness need:**
  - *Consumption* — cheapest, pay-per-execution (first 1M/month free), but can "cold start"
    (a few seconds' delay when idle). Fine for provisioning, which isn't sub-second.
  - *Premium / Flex Consumption* — keeps an instance warm (no cold start) and supports
    **VNet integration** (private networking). Recommended if we need private connectivity
    to on-prem/Zoho Desk or guaranteed instant response. Small fixed monthly cost.
- **Identity & secrets:** the Function App uses a **Managed Identity** to read Key Vault and
  start Automation runbooks — so no secrets are stored in the app itself.
- **Securing the webhook:** Azure function-level auth key **plus** our own shared-secret
  token check (`agent/webhook.py`); HTTPS only.
- **Networking:** public HTTPS by default. To reach private/on-prem resources directly, use
  the Premium plan with VNet integration; the local-AD path avoids inbound holes entirely
  because the Hybrid Worker polls Azure outbound.
- **Monitoring/alerting:** Application Insights captures logs/metrics; failures and
  needs-attention outcomes also post a Teams card via `lib/notify.py` (see "Flagging &
  alerts").
- **Deployment:** push from this git repo to the Function App via `func azure functionapp
  publish` or a CI/CD pipeline (GitHub Actions / Azure DevOps). Updates deploy with no
  downtime.

### Secrets & Key Vault

**Azure Key Vault** is a managed service that stores secrets (passwords, API keys,
certificates) securely so they never live in our code or git repo. How it works:

- **Secrets are named entries.** Each secret is a name → value pair, e.g.
  `zoho-refresh-token` → the actual Zoho Desk refresh token. Values are encrypted at rest and only
  ever sent over TLS.
- **Access is identity-based, not password-based.** Nothing "logs in" to the vault with
  another password. Our Function App has a **Managed Identity** (an identity Azure manages
  for the app); the vault is configured to allow *that identity* to read secrets. So the
  app proves who it is to Azure AD and the vault checks it's on the allow-list (RBAC /
  access policy) — there's no bootstrap secret to leak.
- **Runtime flow.** When the code calls `get_secret("AZURE_CLIENT_SECRET")`
  (`lib/secrets.py`), it asks Key Vault for that secret; the Function App's Managed Identity
  authenticates automatically; Key Vault returns the value over HTTPS; the app uses it in
  memory and never writes it to disk or logs. (Key Vault secret names can't contain `_`, so
  `AZURE_CLIENT_SECRET` maps to `azure-client-secret`.)
- **Every access is logged.** Key Vault records who read which secret and when — useful for
  audits and client security reviews.
- **Rotation without redeploys.** To change a credential, update it in the vault; the app
  picks up the new value on its next read — no code change, no redeploy.
- **Separation of duties.** Engineers can build and deploy the app without ever seeing the
  production secrets; only the vault (and its access policy) holds them.

In dev, `get_secret` reads from environment variables first (handy locally); in Conosco's
Azure tenant it resolves from Key Vault when `KEY_VAULT_URL` is set. Placeholder values are
refused, so nothing ever runs against fake credentials.

### Note on the AI model

The current implementation is **deterministic automation** — Claude (the LLM) is **not
called per ticket**. If we later add AI reasoning to a step (e.g. interpreting free-text
tickets), that would be an HTTPS call from the Function App to the **Anthropic API**
(Anthropic-hosted); nothing extra for Conosco to host.

---

## Testing on your own tenant first

Before pointing the agent at a client, run it end to end against **your own Microsoft
tenant** from your own PC — no Azure deployment needed. `tools/run_ticket.py` runs the real
agent logic against one real Desk ticket:

```
python tools/run_ticket.py "#101"          # PREVIEW: shows what it would do, changes nothing
python tools/run_ticket.py "#101" --live   # does it for real
```

Preview reads the ticket from Desk and your tenant's domains from Microsoft, then prints the
parsed details, the client it identified, and exactly what a live run would do (comment,
status, account) — without writing anything to Desk or Microsoft, sending alerts, or
touching `audit.log` / `state.json`. Quote `"#101"`: `#` starts a comment in most shells.
The long id from the ticket's browser address also works.

**1. Python on your PC** (3.11+), in the repo folder:
```
python -m venv .venv
.venv\Scripts\activate          # Windows   (macOS/Linux: source .venv/bin/activate)
pip install -r requirements.txt
copy .env.example .env           # macOS/Linux: cp .env.example .env
```

**2. Desk statuses** — the five statuses in "Flagging & alerts" above.

**3. Zoho API access.** In the Zoho API console for your data centre
(`api-console.zoho.com`, or `.eu` / `.in` / `.com.au`) add a **Self Client**; put its Client ID
and Secret in `.env` as `ZOHO_CLIENT_ID` / `ZOHO_CLIENT_SECRET`. "Generate Code" with scope
`Desk.tickets.ALL,Desk.search.READ,Desk.basic.READ`, then straight away (codes expire in minutes):
```
python tools/zoho_token.py --region com --code <the code>
```
It saves `ZOHO_REFRESH_TOKEN`, `ZOHO_ORG_ID`, the regional URLs (and the Client ID / secret if
you typed them in) straight into `.env`, showing the token only partly — so nothing secret
appears on screen. If a token is ever exposed, delete the Self Client in the API console
(that invalidates its tokens) and create a new one.

**4. App registration in your tenant** (Entra admin centre → App registrations → New):
add Microsoft Graph **application** permissions `User.ReadWrite.All`,
`Group.ReadWrite.All`, `Organization.Read.All`, `Domain.Read.All`, then **Grant admin
consent**. Create a client secret. In `.env` set `AZURE_CLIENT_ID` (the app's Application ID)
and `AZURE_CLIENT_SECRET`.

**5. A client file for your tenant** — `clients/test-<yourname>.yaml`. Files named
`clients/test-*.yaml` are git-ignored, so your tenant's details never reach the repo:
```yaml
client_id: test-yourname        # must match the file name
identity_path: entra
tenant_id: <your tenant id>     # Entra admin centre → Overview
license_skus: []                # none needed; add e.g. O365_BUSINESS_PREMIUM if you have spares
default_groups: []              # or names of groups that exist in your tenant
usage_location: ZA
approval_required: true
```

**6. A test ticket.** Submit one of the onboarding forms (or email the helpdesk with a
`Label : Value` summary pasted in) where the email addresses use **your tenant's domain**
(e.g. `you@yourtenant.onmicrosoft.com`) — that's how the agent knows it's your "client" —
with a subject such as "New Starter IT Form".

**7. Preview** — `python tools/run_ticket.py "#<number>"`. Check the client, name, username
and plan. Exit code 1 means a live run would flag it, and the output says why.

To check a client's form labels, run `python tools/run_ticket.py "#<number>" --show-labels`
on one of their real onboarding tickets. It lists every question label on the form, marks
the ones the agent uses, and lists the ones it expected but didn't find — **answers are never
shown**, so the output is safe to share. A question that isn't matched (no `-> used as`)
but should be goes in that client's `field_labels`, or in `DEFAULT_FIELD_LABELS` if it's
general wording.

**8. Live, step by step.**
1. `python tools/run_ticket.py "#<number>" --live` → the plan is posted as an internal
   comment and the ticket moves to *Awaiting Approval*.
2. In Desk, set the ticket to **Approved**.
3. Run the same `--live` command again → the account is created in your tenant and the
   ticket moves to *Provisioned*. Running it again does nothing (it remembers, via
   `state.json`).

**9. Check in Entra** that the user exists with the right name and username. The agent
doesn't hand out the temporary password yet, so **reset the password** in Entra to sign in.
Delete the test user afterwards.

Optional: set `TEAMS_WEBHOOK_URL` and run a ticket that can't be matched (e.g. a gmail
address only) to see the Teams alert.

---

## Demo / simulation

`demo/starter-leaver-demo.html` is a **self-contained, no-setup demo** for showing the
concept to clients. Open it in any browser (double-click — no server, no install, no
credentials, no real data). It runs against a built-in **mock tenant**.

- **New Starter** tab — submit a joiner (name, department, title, manager, client) and
  watch the agent stream through each real onboarding step; the new user appears live in
  the directory panel and flips from *Provisioning* → *Active*. Picking a *Hybrid AD*
  client makes the log show the Hybrid Runbook Worker path, useful for explaining the
  architecture mid-demo.
- **Leaver** tab — offboard an existing user (standard or immediate/security event):
  sign-in disabled, sessions revoked, groups stripped, mailbox/files handed over, devices
  wiped, licence reclaimed. User flips to *Disabled* live.
- **Stat bar** contrasts **agent time (~seconds)** against **typical manual time (~2h 45m)**
  — the key client-experience / turnaround message.
- **Pace** selector (top-right): *Presentation (paced)* for a live walk-through, *Fast*,
  or *Instant*.

All data is fake and nothing connects out — the demo is a faithful simulation of the flow,
not a live integration.

---

## Repository structure

```
function_app.py   Azure Functions: zoho_webhook (HTTP) + reconcile_poll (timer)
/agent            orchestrator core, approval gate/dispatcher, reconciliation, webhook auth
/skills           starter-provisioning skill(s): step-by-step process the agent follows
/actions          constrained action layer (create_user, assign_license, add_groups, ...)
  /entra          Microsoft Graph implementations
  /local_ad       Hybrid Runbook Worker / Azure Automation runbook callers
/clients          per-client YAML config + schema + _lookup.yaml (company-name aliases)
/tools            run_ticket.py (run one real ticket: preview / --live), zoho_token.py
/lib              Zoho Desk client, config loader, Graph/Automation transports, state, audit
/config           non-secret settings (poll interval, endpoints)
/tests            unit tests (Zoho Desk parsing, config validation) + mocked action tests
```

---

## Status

Greenfield — see [ROADMAP.md](ROADMAP.md). Currently scaffolding **Phase A**.
Scope: **Starter** process first; **Leaver** reuses the same skeleton (Phase E).
