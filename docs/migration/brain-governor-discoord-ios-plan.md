# Brain / Governor / Discoord / iOS Migration Plan

Last updated: 2026-08-30

This is the canonical implementation and progress tracker for separating
KaosBrain, KaosGovernor, KaosDiscoord, KaosGDD domain services, notifications,
and iOS clients. Update this document whenever a phase starts, its scope
changes, validation is completed, or production is promoted.

This plan tracks architecture work. The older
[infrastructure migration plan](migration-plan.md) remains the source for H3,
H4, office-service, and stateful-service cutovers.

## Current Position

- Current phase: Phase 2, durable PostgreSQL operations and confirmation
  payloads, validated locally on 2026-08-30. Production and backup/restore
  gates remain open.
- Phase 1 remains implemented and validated locally; its changes have not yet
  been committed or deployed separately.
- Production behavior: unchanged by this architecture plan so far.
- Database schema in production: migration `004`; additive migration `005` is
  written and tested but has not been applied to production.
- Working rule: finish and verify one boundary before moving another domain.

## Progress

| Phase | Objective | Implementation | Production | Status |
| --- | --- | --- | --- | --- |
| 0 | Audit current architecture and flows | Complete | No change | Complete |
| 1 | Establish the Governor operation boundary | Complete and tested | Not deployed | Validated locally |
| 2 | Persist operations, confirmations, and pending payloads | Complete and tested | Not deployed | Validated locally |
| 3 | Route every meaningful mutation through Governor | Not started | Not deployed | Planned |
| 4 | Make Brain transport-neutral | Not started | Not deployed | Planned |
| 5 | Isolate KaosDiscoord and notification delivery | Not started | Not deployed | Planned |
| 6 | Add stable iOS APIs and lightweight clients | Pilot read endpoint only | Pilot active | Planned |
| 7 | Remove compatibility debt and finish documentation/CI | Not started | Not deployed | Planned |

Status meanings:

- **Planned**: scope is recorded but implementation has not started.
- **In progress**: code or migration work has started.
- **Validated locally**: implementation and relevant tests pass, but the change
  has not been promoted to production.
- **Production observation**: deployed with compatibility paths retained.
- **Complete**: exit criteria and observation gate passed; rollback remains
  documented.

## Target Ownership

```text
Discord ──> KaosDiscoord ──┬──────────────> KaosGovernor
                           │ deterministic
                           └──> KaosBrain ─> KaosGovernor
                                language

Web / Shortcuts / Scriptable ─────────────> KaosGovernor
                    Ask Kaos ─> KaosBrain ─> KaosGovernor

KaosGovernor ──> domain services/adapters ──> authoritative services
                                            Radicale / Memos / Paperless / HylaFAX
```

Ownership rules:

1. Brain interprets, reasons, answers, and proposes structured actions.
2. Governor deterministically validates, authorizes, confirms, routes, and
   records operations.
3. Discoord transports Discord input and output and owns no domain policy.
4. Domain services execute and preserve their existing sources of truth.
5. Shortcuts and Scriptable are clients, not state stores.
6. Notifications are Governor/domain behavior with replaceable delivery
   adapters, including Pushover and Discord.
7. Deterministic callers do not invoke an LLM.

## Preserved Constraints

- No unnecessary microservices or container split.
- No Radicale, Memos, Paperless, HylaFAX, PACS, or DICOM rewrite.
- No change to the HylaFAX spool, modem, services, or documented
  `setup.cache`/`setup.modem` workaround.
- No second task, memo, calendar, or supplies state store for iOS.
- No broad Governor bearer token stored on an iPhone.
- No API duplication for Discord and iOS.
- No removal of compatibility routes before parity and observation.
- Database changes are additive and rollback-aware.
- Existing H3 operational bot and H4 conversational bot identities remain
  separate even after their Discord code shares a KaosDiscoord package.

## Phase 0 — Repository and Runtime Audit

Status: complete.

Completed:

- Identified Brain, Governor, Discord, API, notification, domain-service,
  Docker, test, and permission paths from the actual repository.
- Confirmed that Brain mutations currently use Governor proposals, while some
  deterministic Discord and web mutations still bypass the central lifecycle.
- Confirmed three transitional API surfaces on ports 8096, 8097, and 8098.
- Confirmed that operation and confirmation tables exist in PostgreSQL schema,
  but the active tool path uses `MemoryDurableGovernorStore` and in-process
  pending dictionaries.
- Confirmed the Pushover outbox is reusable but its worker lifecycle is still
  started by the Discord bot.
- Confirmed the Office Fax Connector and Fax Bridge already form a strong
  boundary around HylaFAX and must remain unchanged.
- Reviewed current plans, operational runbooks, and archived KaosFaxMail
  history.

Exit evidence:

- Current architecture, gaps, target flows, migration phases, risks, rollback,
  and non-goals were reviewed before code changes began.

## Phase 1 — Governor Operation Boundary

Status: implemented and validated locally on 2026-08-30.

Objective:

- Establish one transport-neutral operation lifecycle interface without
  changing current API responses, domain behavior, or deployment topology.

Implemented:

- Added `kaos_governor.operations.GovernorOperations`.
- Added the `DurableOperationStore` protocol so production storage can change
  without changing callers.
- Centralized submission, idempotent start, confirmation creation and approval,
  audit transitions, completion, and failure lifecycle calls.
- Routed all current `/tools` mutation proposals, approvals, and the immediate
  imaging second-look lifecycle through `GovernorOperations`.
- Kept domain execution and pending typed payloads in the existing tool server
  for compatibility; extracting them is intentionally later work.
- Made the Brain service-menu date injectable and removed the calendar test's
  dependency on the wall clock.
- Updated target role documentation to distinguish Brain, Governor, and
  Discoord.

Files:

- `apps/governor/src/kaos_governor/operations.py`
- `apps/governor/src/kaos_governor/__init__.py`
- `apps/governor/tests/test_operations.py`
- `integrations/discord/src/kaos_governor_discord/tools.py`
- `apps/brain/src/kaos_brain/discord_active_control_views.py`
- `apps/brain/tests/test_bot_views.py`
- `docs/architecture/target-architecture.md`
- `docs/architecture/kaosai-brain-governor.md`

Behavior change:

- None intended or observed. Existing routes, confirmation TTL, response
  payloads, service calls, credentials, and process placement are preserved.

Validation:

- Governor: 193 tests passed.
- Governor Discord: 345 tests passed.
- Brain: 317 tests passed.
- Total relevant tests: 855 passed.
- `git diff --check`: clean.

Risk: low. This is an internal lifecycle delegation, not a writer or schema
cutover.

Rollback:

- Revert the Phase 1 source and documentation changes. There is no data or
  database rollback because no migration or deployment was performed.

Release checklist:

- [x] Boundary implementation
- [x] Focused tests
- [x] Governor/Discord regression suite
- [x] Brain regression suite
- [x] Architecture documentation
- [ ] Review and commit
- [ ] Deploy through the existing H3/H4 procedure
- [ ] Verify health and representative proposal/approval in production
- [ ] Complete observation gate

## Phase 2 — PostgreSQL Operation Persistence

Status: validated locally on 2026-08-30; not deployed.

Objective:

- Make operation, confirmation, and normalized pending execution state survive
  process and host restarts.

Implemented locally:

1. Inventory every current pending payload shape for tasks, events, memos, and
   Paperless metadata.
2. Added `005_durable_operation_payloads.sql` without changing migrations
   `001` through `004`.
3. Persist normalized request parameters and the minimum execution payload
   required after confirmation. Never persist attachments, tokens, mail bodies,
   fax documents, or unrelated conversation text in these rows.
4. Added explicit payload schema versions, a 128 KiB limit, prohibited
   credential/binary field names, and cleanup on completion, failure, expiry,
   startup, and normal store activity. Long-lived operation parameters use
   fingerprints instead of memo/task/event body text. A consumed confirmation
   left indeterminate by a process crash is not blindly replayed; after a
   one-hour grace window it is failed as `execution_interrupted` and its payload
   is removed.
5. Implemented `PostgresDurableGovernorStore` against the existing
   `DurableOperationStore` protocol.
6. Use transactions and row locking for idempotent start, single-use approval,
   expiry, completion, and failure.
7. Added explicit `GOVERNOR_OPERATION_STORE=postgres` H3 wiring while retaining
   the memory store for unit tests and deliberately isolated adapters. The
   production setting is not active until deployment.
8. Replaced the nine in-process pending dictionaries in the tool server with
   Governor-owned durable payload retrieval.
9. Proved restart recovery at the HTTP adapter boundary, JSON round-trip
   compatibility for all nine payload kinds, and single-use concurrent
   approval against PostgreSQL.

Likely files:

- `apps/governor/migrations/005_*.sql`
- `apps/governor/src/kaos_governor/durable.py`
- `apps/governor/src/kaos_governor/operations.py`
- `apps/governor/src/kaos_governor/database.py`
- `apps/governor/src/kaos_governor/postgres_durable.py`
- `apps/governor/tests/test_durable.py`
- `apps/governor/tests/test_operations.py`
- `apps/governor/tests/test_postgres_durable.py`
- `integrations/discord/src/kaos_governor_discord/config.py`
- `integrations/discord/src/kaos_governor_discord/main.py`
- `integrations/discord/src/kaos_governor_discord/tools.py`
- `integrations/discord/tests/test_tools.py`
- `deploy/h3-backend/compose.yaml`
- `.github/workflows/test.yaml`

Behavior change:

- Pending confirmations continue to work after a Governor/Discord restart.
- Duplicate and concurrent approvals resolve deterministically.
- Public HTTP contracts remain unchanged.

Crash policy:

- A restart before approval is recoverable from the durable payload.
- A completed response is idempotently terminal and cannot be reopened with
  the same key.
- A crash after confirmation consumption but before the result is recorded is
  treated as indeterminate. The Governor does not auto-replay non-idempotent
  creates; it retains the payload for one hour for diagnosis, then marks the
  operation `execution_interrupted` and removes the payload.

Risk: medium. Transaction boundaries and payload compatibility can affect
confirmed writes.

Required tests:

- memory/PostgreSQL store contract parity
- migration on an empty and migration-004 database
- idempotency conflict and replay
- concurrent single-use approval
- expiry boundary
- completion/failure audit transitions
- restart between proposal and approval for every pending payload kind
- no secret or binary payload persistence
- existing Governor, Discord, and Brain regression suites

Rollback:

- Keep migration `005` additive.
- Allow the process to select the memory store during rollback while the new
  tables/columns remain unused.
- Do not drop Phase 2 schema during an application rollback.
- Retain compatibility endpoints and the previous image until the observation
  gate passes.

Exit criteria:

- [x] Migration reviewed and tested on empty and populated migration-004 schemas
- [x] PostgreSQL store passes the durable lifecycle contract tests
- [x] Restart recovery and serialization pass for every mutation payload kind
- [x] All relevant regressions pass
- [ ] Backup/restore includes new operation state
- [ ] Production promotion approved
- [ ] Observation gate completed

## Phase 3 — Route Mutations Through Governor

Status: planned.

Objective:

- Make all meaningful Kaos mutations use `GovernorOperations` and a registered
  deterministic domain handler.

Migration order:

1. task and supplies create/edit/complete/reopen/delete
2. Memos create/edit/delete
3. Paperless metadata and document intake
4. event creation and remaining calendar/family writers
5. outbound fax and mail mutations
6. settings, recurrence, ledger, and notification acknowledgements

Each domain moves independently. Reads may continue through existing service
interfaces. Compatibility Discord/web handlers delegate to Governor rather
than being deleted.

Affected areas:

- `integrations/discord/tasks.py`, Memos, inbox, fax, mail, and organizer paths
- `apps/governor/src/kaos_governor/api.py`
- family portal calendar write proxy
- Governor domain modules and boundary tests

Risk: medium to high per writer. Fax and deletion require exact confirmation;
family calendar routing requires careful scope preservation.

Tests and observation:

- add domain handler contract tests before switching each writer
- verify actor/scope, idempotency, confirmation, audit, and exact backend call
- deploy and observe one writer at a time
- retain the previous handler as a rollback path until reconciliation passes

Exit criteria:

- no identified Discord or web mutation bypasses Governor
- deterministic operations remain callable without Brain
- destructive and external-send confirmation policy is centralized

## Phase 4 — Transport-Neutral Brain

Status: planned.

Objective:

- Separate interpretation/reasoning from Discord connection and presentation.

Planned implementation:

- Add a transport-neutral Brain service interface for interpret, answer, and
  structured action proposal.
- Keep the existing Guard, deterministic parsers, planner integration, and
  Governor client behavior.
- Make the current `BrainBot` call the service before moving views or renaming
  packages.
- Ensure Brain has no domain-service write credentials.
- Add tests using non-Discord actor/context requests.

Risk: medium. Conversation context, clarification state, and active controls
must preserve current behavior.

Rollback: retain the existing `BrainBot` entry point and compatibility wiring
until request/response parity passes.

## Phase 5 — KaosDiscoord and Independent Notifications

Status: planned.

Objective:

- Isolate Discord transport code and make immediate Pushover delivery work
  independently of the Discord gateway lifecycle.

Planned implementation:

- Introduce a KaosDiscoord package boundary for the H4 conversational and H3
  operational adapters without merging their bot identities.
- Move Discord views, formatting, IDs, attachments, channel policy, and
  interactions into the adapter boundary.
- Keep deterministic commands on the Governor path and natural-language
  requests on the Brain path.
- Move notification scheduling/outbox lifecycle to Governor-owned workers.
- Treat Pushover and Discoord as independent delivery adapters so one failure
  cannot block the other.
- Preserve simple Apple Watch copy and native iOS task notifications.

Risk: high around persistent Discord custom IDs, state files, channel IDs, and
duplicate notification delivery.

Rollback: retain current process commands, bot tokens, state paths, and
compatibility imports through the observation period.

## Phase 6 — Stable iOS Interfaces

Status: planned; read-only supplies pilot exists.

Objective:

- Provide narrow authenticated APIs for Shortcuts and a small Scriptable client
  without duplicating source-of-truth data.

Planned API capabilities:

- active and completed tasks
- create/edit/complete/reopen task
- agenda and event creation
- memo list/search/create/edit
- supplies list and actions
- combined search
- confirmation approval
- `Ask Kaos` through Brain

Rules:

- use scoped mobile credentials, never the broad Governor token
- deterministic actions call Governor directly
- `Ask Kaos` is the only normal mobile path that requires Brain
- continue using native Calendar/Reminders through Radicale where they are the
  better interface
- keep `/shortcuts/supplies` as a compatibility route during migration

Required deliverables:

- versioned API contract and authentication tests
- committed example Shortcuts instructions
- focused Scriptable client for richer on-demand lists/actions
- no background state database on iOS

## Phase 7 — Cleanup, CI, and Deprecation

Status: planned.

Objective:

- Remove transitional ownership only after parity and production observation.

Planned work:

- update all architecture, runtime, security, and recovery documentation
- add boundary and dependency tests preventing Discord imports in Governor
- include Fax Bridge tests explicitly in CI
- inventory compatibility endpoints and publish deprecation dates
- remove unused direct writers and duplicated APIs one at a time
- reconcile service naming without a rename-first refactor
- verify backups and a complete recovery exercise

Exit criteria:

- one documented mutation boundary
- Brain optional for deterministic operation
- Discord replaceable as a transport
- notifications independent of Discord
- stable scoped mobile interfaces
- no duplicate authoritative state
- all compatibility removals have completed observation and rollback gates

## Confirmation Policy Target

| Operation | Initial policy |
| --- | --- |
| Read/query | No confirmation |
| Explicit reversible single create/complete | Execute with receipt; optional undo where supported |
| Ambiguous request | Clarify before proposing |
| Delete or bulk edit | Exact expiring confirmation |
| Paperless metadata overwrite | Exact expiring confirmation |
| External fax transmission | Exact destination and file confirmation |
| Infrastructure/security operation | Outside normal Brain tools or separately hardened |

Current behavior is preserved until the relevant domain migrates in Phase 3.

## Progress Log

| Date | Phase | Change | Evidence | Production impact |
| --- | --- | --- | --- | --- |
| 2026-08-30 | 0 | Completed repository, live-service, documentation, boundary, and test audit | Current architecture and gap analysis reviewed | None |
| 2026-08-30 | 1 | Added `GovernorOperations`, store protocol, tool delegation, boundary tests, and stable Brain date injection | 193 Governor + 345 Discord + 317 Brain tests passed | None; not deployed |
| 2026-08-30 | Plan | Added this canonical tracker and aligned architecture terminology | Documentation review and `git diff --check` | None |
| 2026-08-30 | 2 | Started PostgreSQL operation persistence and pending-payload inventory | Implementation in progress | None |
| 2026-08-30 | 2 | Added migration 005, PostgreSQL store, durable versioned payloads, restart recovery, expiry/interruption cleanup, production store wiring, and CI PostgreSQL coverage | 200 Governor unit/contract + 9 PostgreSQL integration + 349 Discord + 317 Brain tests; H3 preflight and Compose render passed | None; not deployed, production remains on migration 004 |

## How to Update This Tracker

For every implementation turn:

1. Mark the phase **In progress** before broad code changes.
2. Record the exact scope and any changed assumptions.
3. Update the affected-files, risk, tests, and rollback sections.
4. Record test counts and production impact in the progress log.
5. Distinguish local validation, commit, deployment, and observation; do not
   call a phase complete merely because code exists.
6. Never mark a production gate complete without direct evidence.
