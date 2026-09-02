# KaosSystemOperator Access Plan

Status: Phase 2 runbook planning, local dry-run planner, and non-networked mock
lifecycle implemented; read-only `system.status` confirmed in Discord;
execution remains disabled.

Last updated: 2026-09-01

## Purpose

KaosSystemOperator is a separate Codex working session for real system
operations. It may manage Kaos servers and repositories, but it must not become
an unrestricted shell hidden behind Discord or AI chat.

The durable shared context is this repository, not Codex home state. Every
operator session reads these docs before acting and updates them after material
work.

Required session bootstrap:

```text
git status --short --branch
git pull --ff-only (only when the worktree is clean and the branch can fast-forward)
docs/operator/kaos-system-operator-access-plan.md
docs/operator/session-handoff.md
docs/operator/operation-log.md
docs/architecture/security-boundaries.md
docs/architecture/brain-system-operations.md
docs/migration/brain-governor-discoord-ios-plan.md
```

## Control Path

```text
Discord #brain / Codex operator session
  -> KaosBrain or KaosSystemOperator interprets
  -> KaosGovernor validates actor, target, policy, preflight, confirmation
  -> host executor runs one versioned allowlisted runbook
  -> verification result and operation log are saved
```

The model may draft, explain, inspect, and propose. It may not authorize itself
or execute arbitrary generated commands on production systems.

## Access Stages

| Stage | Name | Allowed access | Write authority |
| --- | --- | --- | --- |
| 0 | Repo and docs | Read/write repo docs, inspect git status/diff, inspect committed code | Commit documentation and non-runtime plans |
| 1 | Read-only observe | Health endpoints, bounded logs, Docker/container status, disk/memory, git status, backup freshness, pending updates | None |
| 2 | Proposal writes | Draft runbooks, scripts, config patches, migration plans, rollback plans | Repo changes only; no production execution |
| 3 | Non-critical governed actions | Restart allowlisted non-critical services; reload app services; run approved diagnostics | Only after exact confirmation and audit |
| 4 | Maintenance runbooks | Package update, deploy pinned release, reboot H3/H4, rollback release | Only after preflight, backup check, exact confirmation, and verification |
| 5 | High-risk systems | PACS, databases, OS/security, firewall, secrets, destructive cleanup | Separate hardened maintenance flow; not normal chat approval |

Current production state: Stage 1 partial. `system.status` is deployed through
KaosBrain and KaosDiscoord and was confirmed working from Discord `#brain` on
2026-09-01. Stage 2-5 execution is not enabled.

Current repository state: the Stage 2 schema and eleven dry-run-only
catalog entries are under [`runbooks/`](../../runbooks/README.md). They are
planning artifacts only and contain no executor implementation or production
write authority.

A repository-local planner validates those catalog entries and emits inert,
normalized plan JSON. It accepts only the fixed operation allowlist and
schema-declared parameters. It has no host adapter, subprocess call, network
client, command mapping, API wiring, or production integration.

The committed catalog manifest pins the exact schema and catalog file set by
SHA-256. Changed, missing, additional, or stale entries fail closed. This is an
unsigned Git-reviewed integrity baseline; it introduces no signing secret.

The non-networked mock adapter accepts only a plan it can exactly re-derive
from the pinned catalog. It simulates preflight, read-only verification, and an
in-memory audit receipt using deterministic fake evidence. Confirmation-gated
restart planning stops without action. It is not a host executor.

Six update contracts split routine system packages and H3 container images
into check, frozen-plan, and apply stages. Both apply stages require a SHA-256
frozen-plan reference and ten exact confirmation bindings. Docker Engine,
kernel, security-policy, database, and PACS updates remain outside this routine
track.

## Host Scope

### H4 `kaosbrain`

Allowed targets:

- KaosBrain service
- OpenClaw gateway and reauth helper
- local model runtime health
- Brain logs and health
- repo sync state

Initial allowed operations:

- `system.status`
- `system.git_status`
- `system.logs_tail`
- `system.disk_status`
- `system.memory_status`
- `system.check_updates`

Future governed operations:

- `service.restart` for KaosBrain/OpenClaw only
- `repo.deploy` for pinned KaosBrain release
- `system.reboot` only after explicit downtime confirmation

### H3 `kaosgdd`

Allowed targets:

- KaosGovernor API and worker
- KaosDiscoord runtime
- personal/family KaosGDD PWA
- Radicale, Memos, Paperless, HylaFAX adapters
- Caddy/cloudflared edge status
- repo sync state

Initial allowed operations:

- `system.status`
- `system.git_status`
- `system.logs_tail`
- `system.disk_status`
- `system.memory_status`
- `system.backup_status`
- `system.check_updates`

Future governed operations:

- restart `kaos-governor-worker`
- restart `kaos-governor-discord`
- rebuild/deploy PWA static assets
- deploy pinned Governor/worker release
- reboot H3 only after explicit downtime confirmation

### KaosPACS / office services

Allowed initial access:

- read-only health
- bounded logs
- backup freshness
- explicit architecture/runbook planning

Denied by default:

- DICOM mutation
- database writes
- PACS service restart during clinic operation
- OS/security/package changes
- firewall/network changes

These require a separate hardened maintenance track.

## Denied Capabilities

KaosSystemOperator must not receive or use:

- unrestricted sudo
- raw Docker socket access from AI chat
- production SSH keys embedded in prompts or tool payloads
- secrets, token files, `.env` contents, OAuth refresh tokens, database
  passwords, or private keys
- arbitrary shell execution requested through Discord
- arbitrary package-manager arguments generated by the model
- direct production database writes
- destructive recursive file operations outside an exact confirmed target
- Gmail/mail deletion outside a governed mailbox action with confirmation
- PACS/DICOM mutation outside a dedicated clinical maintenance flow

## Runbook Contract

Every executable system operation must be a named runbook with a stable
contract.

```json
{
  "operation": "service.restart",
  "target": "kaosbrain.service",
  "host": "kaosbrain",
  "parameters": {},
  "preflight": {
    "currentState": "healthy",
    "backupRequired": false,
    "expectedDowntime": "under 30 seconds"
  },
  "confirmation": {
    "required": true,
    "expiresAt": "ISO-8601",
    "exactSummary": "Restart KaosBrain on H4 kaosbrain"
  },
  "verify": {
    "checks": ["service active", "health ready", "discord connected"]
  },
  "rollback": {
    "available": false,
    "reason": "restart-only operation"
  }
}
```

Model output never becomes the command. The executor maps `operation` and
`target` to a trusted implementation.

## Confirmation Rules

Read-only observe operations do not need confirmation.

Required confirmation for write operations must include:

- host
- service or repo target
- exact action
- expected interruption
- backup status when relevant
- rollback path when relevant
- expiry

For restart/reboot/update/deploy, casual `ok`, `go`, or `approved` is
insufficient. The confirmation prompt must bind the normalized operation and
the UI/button/approval must reference that operation ID.

## Script Creation Policy

KaosSystemOperator may draft scripts, but script execution is a separate
operation.

Allowed:

- create scripts under a repo-controlled runbook/scripts directory
- run shellcheck/static review where available
- commit proposed scripts
- document exact intended execution

Not allowed without a second confirmation:

- execute a newly generated script on production
- execute copied one-off shell from Discord
- modify live secrets or credentials
- run destructive cleanup generated by the model

## Shared Session State

Operator sessions share context through files:

- `session-handoff.md`: current goal, last safe state, next action
- `operation-log.md`: append-only material operations and receipts
- repo commits: durable implementation history
- architecture docs: policy and migration decisions

At the start of a new KaosSystemOperator Codex session:

1. inspect `git status --short --branch` before changing the checkout;
2. when the worktree is clean, update from `origin/main` using fast-forward-only
   synchronization;
3. stop for reconciliation rather than pulling when the worktree is dirty or
   the local branch has diverged;
4. read the required bootstrap docs from the synchronized checkout;
5. inspect current production health if the task touches runtime;
6. state the intended operation class before write actions.

At the end of a material session:

1. update `session-handoff.md`;
2. append `operation-log.md`;
3. commit documentation/code changes when appropriate;
4. push to main when GitHub auth is available;
5. sync H4/H3 repos when production state depends on the commit.

## Initial Implementation Plan

1. Keep current `system.status` in production observation.
2. Add personal PWA Settings/Admin read-only status view. Keep the PWA as a
   system observation surface only; do not add restart, deploy, reboot, shell,
   package-update, or other system write controls to PWA. A navigation-only
   link to Discord `#brain` is allowed for operator conversation.
3. Define repo runbook directory and JSON schema for operator operations.
4. Add dry-run-only host executor prototype for H4.
5. Add one allowlisted non-critical restart with exact confirmation.
6. Add H3/H4 deploy/reboot only after backup verification is automated.
7. Treat PACS/office operations as a separate project.

## Phase 2 Runbook Planning Baseline

The initial version 1 contract is
[`runbooks/schema/runbook.schema.json`](../../runbooks/schema/runbook.schema.json).
It requires every catalog entry to identify the host, target, exact action,
bounded parameters, preflight, confirmation policy, verification, rollback
note, and durable operation-log fields.

The schema fixes all current entries to `dry-run-only` with
`productionWritesEnabled: false`. The initial catalog covers:

- `system.status`;
- `system.git_status`;
- `system.disk_status`;
- `system.logs_tail`, with a maximum 200-line bound; and
- `service.restart` planning for the allowlisted H3 Governor worker.

The update-planning extension also covers:

- `system.check_updates`, `system.plan_updates`, and
  `system.apply_updates` for an H3 routine-package planning boundary; and
- `containers.check_updates`, `containers.plan_update`, and
  `containers.apply_update` for pinned H3 Kaos backend image planning.

The restart entry records the future confirmation binding and verification
requirements but cannot perform a restart. No host executor, command mapping,
API route, deployment configuration, credential, or production integration is
included in this phase.

The local planner under `runbooks/planner/` loads only fixed catalog filenames,
validates each selected entry against the version 1 schema, normalizes declared
parameters and defaults, and emits a deterministic dry-run operation ID plus
manifest and catalog digests. Those digests are bound into the operation ID.
Every output explicitly records that production writes are disabled and
execution did not occur.

The mock lifecycle adapter completes the repository-only planning prototype.
Before any real read-only host adapter is designed, this boundary requires a
security review covering process isolation, catalog provenance authority,
credential absence, data redaction, audit ownership, and deployment topology.
