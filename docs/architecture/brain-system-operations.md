# Brain as Kaos Gateway and System Operator

Decision date: 2026-08-30

Status: read-only status slice deployed and Discord-confirmed; execution
capabilities are not yet enabled.

## Decision

KaosBrain has two long-term user-facing roles:

1. a natural-language gateway into KaosGDD domains; and
2. a conversational system-operations console for H4 KaosBrain/KaosAI, H3+
   KaosGDD, and separately isolated KaosPACS/office services.

Brain is not the privileged runner. It interprets, explains, diagnoses, and
proposes typed operations. KaosGovernor owns policy, confirmation, audit, and
operation state. A restricted executor beside each managed host or service
runs only trusted, allowlisted runbooks.

## Target Flow

```text
Discord #brain / future Ask Kaos client
  -> KaosBrain interprets or answers
  -> KaosGovernor validates actor, target, policy, and preconditions
  -> exact confirmation when required
  -> restricted host executor selects a trusted runbook
  -> verification and durable receipt
  -> rollback when the runbook defines and triggers it
```

No model-produced text is accepted as executable shell or an arbitrary binary
selection. The model never receives SSH keys, a Docker socket, secrets, or the
ability to authorize its own action.

## Capability Classes

| Class | Examples | Initial policy |
| --- | --- | --- |
| Observe | Health, versions, disk, backup freshness, pending updates | Read-only, immediate |
| Explain | Diagnose a failed probe, summarize logs or release notes | Read-only, untrusted content treated as data |
| Plan | Produce ordered upgrade/preflight/rollback plan | No execution |
| Reversible operation | Restart an allowlisted non-critical service | Exact target confirmation and audit |
| Deployment | Deploy a pinned Kaos release or roll it back | Backup/preflight gate, expiring confirmation, verification |
| Critical infrastructure | PACS/database/OS/security changes | Hardened maintenance flow; never generic chat approval |
| Arbitrary administration | Shell, sudo, raw Docker, secret access | Not exposed to Brain |

## Typed System Operations

The future contract may include narrow operations such as:

```text
system.status
system.check_updates
system.plan_upgrade
system.verify_backup
system.restart_service
system.deploy_release
system.verify_release
system.rollback_release
```

These are operation names, not shell aliases. Trusted configuration maps a
validated target to a versioned runbook. Model output must not contain service
URLs, credentials, filesystem paths, package-manager arguments, or commands.

## Upgrade Lifecycle

Every governed deployment follows an explicit state machine:

```text
discover -> plan -> preflight -> confirm -> execute -> verify
                                      |                 |
                                      +-> expire        +-> complete
                                                        +-> rollback
```

Preflight records the current and requested version, health state, backup
status, storage requirements, expected interruption, dependencies, and
rollback artifact. The final confirmation is bound to that normalized plan,
actor, target versions, and expiry. A model-interpreted `yes` is insufficient.

## Host Isolation

- H4 exposes only runbooks for KaosBrain, KaosAI/OpenClaw, local model runtime,
  and their health checks.
- H3+ owns KaosGDD application deployments, Governor workers, migrations,
  backups, and service-edge checks.
- KaosPACS and office-critical services retain a separate local executor and
  stricter maintenance policy. DICOM receipt and clinic operation must not
  depend on Discord, H4, or an OpenAI model being available.
- A compromised or unavailable Brain cannot expand an executor's allowlist.

## Current State and Migration

The repository already contains read-only maintenance/health probes and a
KaosDiscoord restart path with an explicit allowlist, dry-run default, timeout,
and audit state. Brain now exposes the first operator operation:
`system.status`. It is read-only, deployed in commit `1f2a5e0`, goes through
the authenticated Governor Brain tools API, and renders existing KaosDiscoord
health/service state in the H4 `#brain` path. The user confirmed the live
Discord response on 2026-09-01.

Brain Guard still rejects shell, Docker, database, restart, deployment, and
arbitrary admin intents. That rejection remains in place while the control
plane is extracted.

The concrete access plan for a separate Codex operator session is maintained in
[KaosSystemOperator Access Plan](../operator/kaos-system-operator-access-plan.md).

Incremental delivery:

1. Move read-only system inventory and health state behind Governor-owned APIs.
   Initial `system.status` is available to Brain from KaosDiscoord runtime
   health state.
2. Expose `system.status` to the personal admin PWA as read-only display only.
   The PWA must not expose restart, deploy, reboot, shell, package-update, or
   other system write controls. It may include a navigation-only link to
   Discord `#brain` for operator conversation.
3. Define signed/versioned runbook contracts and a dry-run-only executor.
4. Add one non-critical restart operation with exact confirmation and audit.
5. Add pinned application deployment and rollback only after backup and
   recovery tests pass.
6. Design PACS/office operations as a separate high-risk project; do not grant
   H4 general host access.

## Availability Rule

Deterministic status and operation APIs remain callable without Brain. Every
managed service continues its normal work if Discord, H4, OpenClaw, or the
hosted model is unavailable.
