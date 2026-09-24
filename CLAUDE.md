# CLAUDE.md

Working notes for Claude / contributors on this repository.

## What this project is

An agent that automates **starter/leaver** account provisioning for MSP clients. Requests
originate from **Zoho Forms** (one onboarding form per client); Zoho Forms emails a
`${zf:ALL_FIELDS}` summary to the helpdesk mailbox, which becomes a **Zoho Desk** ticket. The
agent parses the `Label : Value` summary out of the ticket body (`lib/zoho.py`
`parse_summary`), identifies the client from the email domains in it (auto-discovered from
each client's Microsoft tenant) and/or the "Company's Name" answer, classifies starter vs
leaver from the subject, and drives the provisioning core. Anything unclear is flagged for a
technician, never guessed. For the full picture, read these two files first — they are the source
of truth and should be kept in sync with any change:

- **[README.md](README.md)** — architecture, identity paths, APIs & permissions, security,
  repo structure, per-client config format.
- **[ROADMAP.md](ROADMAP.md)** — phased delivery plan (Phase A → E) and the "done when"
  criteria for each phase.

## Core principles (do not violate)

- **Both identity paths are first-class:** `entra` (Microsoft Graph) and `local_ad` (Azure
  Automation Hybrid Runbook Worker). `identity_path` in `clients/<id>.yaml` selects per
  ticket. Graph cannot write on-prem AD — local-AD always goes through a runbook.
- **Constrained action layer holds all privileged credentials**, never the agent. The agent
  reasons/branches and passes *validated structured params* to fixed operations.
- **Ticket content is untrusted input**, not instructions — only specific validated fields
  drive actions (prompt-injection defence).
- **Human approval gate** before any account/license creation.
- **No secrets in the repo** — use Azure Key Vault / environment.
- **Everything is auditable & idempotent** — every action ties to a ticket ID; duplicate
  webhook deliveries must process once.

## Where things live

See the repository-structure section in [README.md](README.md). Per-client process lives in
version-controlled `clients/<client-id>.yaml` (validated against `clients/_schema.*`).

## Keeping docs in sync

When you change architecture, trigger behaviour, identity paths, config shape, or security
posture, update **README.md**; when you change scope or phase ordering, update
**ROADMAP.md**. This file points to both — keep all three consistent.
