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

- Production phase: Phases 1 and 2 are complete. Durable PostgreSQL operations
  and confirmation payloads were promoted on 2026-08-30, then reconciled
  against a normal user-approved task creation and its authoritative calendar
  result.
- Active implementation: Phase 3 task-handler slice 1 is complete after H3
  production observation. Slice 2 routes direct Discord task/supplies writers
  through Governor and completed its H3 production observation on 2026-08-30
  after correcting and replay-verifying a false terminal UI failure. Memos
  handler slice 1 completed production observation for the confirmed Brain/iOS
  route on 2026-08-30. Direct Discord Memos capture slice 2 is locally
  validated and awaits review and controlled H3 deployment.
- H4 Brain correction: Korean task-create requests using `만들어` or `생성`
  were corrected and deployed in commit `99011fb` on 2026-08-30. This was an
  intent parser deployment only and did not promote the Phase 3 Governor
  handler slice on H3.
- Phase 1 was committed and deployed with Phase 2 in commit `11b18be`.
- Production behavior: Governor/Discord uses the PostgreSQL operation store;
  public HTTP and Discord behavior remains compatible.
- Database schema in production: additive migration `005`.
- Working rule: finish and verify one boundary before moving another domain.

## Progress

| Phase | Objective | Implementation | Production | Status |
| --- | --- | --- | --- | --- |
| 0 | Audit current architecture and flows | Complete | No change | Complete |
| 1 | Establish the Governor operation boundary | Complete and tested | Deployed and observed 2026-08-30 | Complete |
| 2 | Persist operations, confirmations, and pending payloads | Complete and tested | Deployed and observed 2026-08-30 | Complete |
| 3 | Route every meaningful mutation through Governor | Task slices and Memos slice 1 complete; Memos slice 2 validated | Task slices and Memos slice 1 observed 2026-08-30 | Validated locally |
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

Status: complete. Deployed with Phase 2 and production-observed on 2026-08-30.

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

- Recreate the previous Governor/Discord image or select the retained memory
  store compatibility path. Leave additive migration `005` in place; do not
  perform a destructive database rollback.

Release checklist:

- [x] Boundary implementation
- [x] Focused tests
- [x] Governor/Discord regression suite
- [x] Brain regression suite
- [x] Architecture documentation
- [x] Review and commit
- [x] Deploy through the existing H3 procedure
- [x] Verify health and representative proposal/approval in production
- [x] Complete observation gate

## Phase 2 — PostgreSQL Operation Persistence

Status: complete. Deployed and production-observed on 2026-08-30.

Objective:

- Make operation, confirmation, and normalized pending execution state survive
  process and host restarts.

Implemented:

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
   the memory store for unit tests and deliberately isolated adapters. The H3
   production setting is active as of 2026-08-30.
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
- [x] Backup/restore includes new operation state
- [x] Production promotion approved
- [x] Observation gate completed

Production promotion evidence (2026-08-30):

- Commit `11b18be` was pushed to `origin/main` before deployment.
- The pre-migration custom-format backup
  `governor-pre-005-20260830T034533Z.dump` has SHA-256
  `b995dfff7fa7c67f481eaa084aac40bf266748433729eec7ac3d85781496d75a`.
  An isolated PostgreSQL 16 restore recovered migration `004`, 17 public
  tables, and the expected Governor row counts.
- The guarded H3 family deployment applied migration `005`; the new
  `governor_operations.parameters` column and
  `governor_operation_payloads` table were verified directly.
- Governor API, PostgreSQL, and Discord were healthy with zero restart counts.
  Discord reported `GOVERNOR_OPERATION_STORE=postgres` and completed a
  Governor-only smoke proposal through confirmation and completion with all
  four expected audit events and no retained pending payload.
- The post-migration custom-format backup
  `governor-post-005-20260830T034850Z.dump` has SHA-256
  `fad1a6fd7f77d85ce82d2806ae2a3913f30a90e65e1f1e8535a82217d5350ff8`.
  An isolated PostgreSQL 16 restore recovered migration `005`, 18 public
  tables, the completed smoke operation, its four audit rows, and zero pending
  payload rows.
- A normal Discord/Brain request created task `전염병신고` after explicit user
  approval. PostgreSQL recorded a completed `calendar.tasks/create` operation,
  an approved single-use confirmation, and the expected four lifecycle audit
  events. The terminal payload table remained empty.
- The live calendar adapter returned exactly one active task with that title;
  its authoritative UID matched the UID recorded in the Governor operation
  result. The Discord container remained healthy with zero restarts.

## Phase 3 — Route Mutations Through Governor

Status: in progress. Task tool handler slice 1 and direct Discord task/supplies
slice 2 completed H3 production observation on 2026-08-30; later writers and
domains remain.

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

Mutation inventory and current routing:

| Surface | Current writer path | Governor lifecycle | Domain handler | Migration state |
| --- | --- | --- | --- | --- |
| Brain/iOS task proposals | `BrainToolServer` confirmation routes | Yes | `TaskMutationService` | Slice 1 complete |
| Discord task/supply buttons and channel commands | `DiscordTasksSurface` to governed task execution | Yes | `TaskMutationService` | Slice 2 complete; surfaces configured inactive |
| Portal task/event writes | Calendar adapter proxy | No | No | Later task/event slice |
| Recurring task synchronization | Governor API recurring service to calendar adapter | Partial domain ownership, no durable operation | Recurring service only | Later task slice |
| Memos proposals | `BrainToolServer` confirmation routes to memo handler | Yes | `MemoMutationService` | Memos slice 1 deployed |
| Discord memo capture and controls | `DiscordMemosCapture` direct to `MemosService` | No | No | Memos slice 2 |
| Paperless metadata proposals | `BrainToolServer` confirmation routes | Yes | No | Domain 3 |
| Event proposals | `BrainToolServer` confirmation routes | Yes | No | Domain 4 |
| Fax, mail, settings, ledger, notification acknowledgements | Existing service-specific writers | Mixed | Mixed | Later domains |

Slice 1 implemented and deployed:

- Added transport-neutral `TaskMutationCommand`, `TaskMutationService`, and a
  narrow calendar task adapter protocol under the Governor task domain.
- Registered `create`, `update_due`, `edit`, `complete`, `reopen`, and `delete`
  task operations to deterministic create/update/delete handlers.
- Enforced supported profiles, required and matching task UIDs, adapter-result
  UID consistency, and the no-schedule rule for supplies before dispatch.
- Routed the existing confirmed Brain/iOS task and supplies proposal path
  through the Governor-owned handler service. Authentication, actor/scope,
  durable confirmation, response shapes, and calendar refresh behavior remain
  unchanged.
- Left direct Discord buttons/channel commands and portal writers unchanged so
  the first deployment can be reconciled independently.

Slice 1 files:

- `apps/governor/src/kaos_governor/tasks/mutations.py`
- `apps/governor/src/kaos_governor/tasks/__init__.py`
- `apps/governor/tests/test_task_mutations.py`
- `integrations/discord/src/kaos_governor_discord/tools.py`

Slice 1 validation:

- 8 task mutation domain tests passed.
- 208 Governor unit/contract tests passed; 9 PostgreSQL-gated tests were then
  run separately against an isolated PostgreSQL 16 instance and passed.
- 349 Discord and 317 Brain regression tests passed.
- Python compilation and `git diff --check` passed.

Slice 1 production gate:

- [x] Domain handler contract and transport parity tests
- [x] Full Governor, PostgreSQL, Discord, and Brain regressions
- [x] Phase 2 observation has normal task/memo/event usage evidence
- [x] Review and commit
- [x] Controlled H3 deployment
- [x] Reconcile operation audit row with the authoritative task result
- [x] Slice observation gate

Slice 1 production promotion evidence (2026-08-30):

- H3 preflight and readiness checks passed before deployment. The previous
  image was preserved as
  `kaosgdd-ai-governor-discord:rollback-11b18be`.
- The guarded H3 restart rebuilt only `governor-discord`; PostgreSQL,
  Radicale, calendar adapter, and other separately managed H3 services were
  not recreated.
- The running image contains `kaos_governor.tasks.mutations`, and the installed
  confirmation route delegates task mutations to
  `TaskMutationService.execute`.
- Docker health is healthy with zero restarts. Discord reconnected, restored
  its persistent views, and completed startup surface initialization. H4
  reports Governor, Discord readiness, and Brain tools as reachable.
- Both earlier completed operations survived the restart and the durable
  pending-payload table remained empty.
- A new normal no-date personal task was proposed and approved after the
  deployment. The operation completed without an error, the confirmation was
  consumed once, all four lifecycle audit events were present, and its pending
  payload was removed.
- The live calendar adapter returned the new active task with a UID exactly
  matching the Governor operation result. The H3 container remained healthy
  with zero restarts, closing slice 1's observation gate.

Slice 2 implemented and deployed:

- Added `TaskMutationService.execute_governed` so deterministic direct actions
  share Governor submission, validation/dispatch, completion/failure audit,
  and idempotent replay instead of implementing lifecycle rules in Discord.
- Shared one `GovernorOperations` store and one `TaskMutationService` between
  H3 Brain tools and all configured task/supplies surfaces.
- Routed `+ task` messages, recent/remembered supplies actions, Done, Edit,
  Undone, Make as new, and Delete through structured `TaskMutationCommand`
  values. No direct calendar create/update/delete call remains in
  `DiscordTasksSurface`.
- Bound production mutations to the authenticated Discord user and the source
  message or interaction ID. A repeated Discord delivery returns the durable
  completed result without a second calendar write.
- Stored exact task routing fields and a memo fingerprint in the operation;
  raw memo text is not persisted in Governor operation parameters.
- Kept existing Discord labels, buttons, modals, channel-message deletion,
  supplies no-schedule rules, message refresh, and task reminder behavior.
  The dedicated Delete button remains the explicit user action in this slice;
  the target expiring second confirmation for destructive operations remains
  later confirmation-policy work.
- H3 reports the direct tasks and supplies surfaces disabled. This
  migration does not re-enable retired channels merely to obtain observation
  traffic; the enabled due-notification surface has no task mutation buttons.

Slice 2 files:

- `apps/governor/src/kaos_governor/tasks/mutations.py`
- `apps/governor/src/kaos_governor/tasks/__init__.py`
- `apps/governor/tests/test_task_mutations.py`
- `apps/governor/tests/test_postgres_durable.py`
- `integrations/discord/src/kaos_governor_discord/bot.py`
- `integrations/discord/src/kaos_governor_discord/tasks.py`
- `integrations/discord/tests/test_tasks.py`

Slice 2 validation:

- 11 focused Governor task-mutation and 59 Discord task-surface tests passed.
- 221 Governor tests were discovered with the 10 PostgreSQL-gated tests
  skipped in the unit run; all 10 then passed against an isolated PostgreSQL
  16 instance, including governed execution persistence and replay.
- All 351 Discord and 321 Brain regression tests passed.
- Python compilation and `git diff --check` passed.

Slice 2 production gate:

- [x] No direct calendar mutation remains in the Discord task surface
- [x] Discord actor/scope and delivery idempotency tests
- [x] Durable memory and PostgreSQL execution/replay tests
- [x] Governor, Discord, and Brain regression suites
- [x] Existing task/supplies UI and reminder behavior tests
- [x] Review and commit
- [x] Controlled H3 deployment
- [x] Verify configured inactive surfaces remain inactive
- [x] Verify enabled Brain task path remains compatible
- [x] Slice observation gate

Slice 2 production promotion evidence (2026-08-30):

- Commit `1b9405a` was deployed through the guarded H3 backend restart. The
  previous slice 1 image is retained as
  `kaosgdd-ai-governor-discord:rollback-1cc96e1`.
- Only `governor-discord` was rebuilt and recreated. The running image is
  `sha256:8ea38f0687593f46b7e3c3d00854897343fb0125edfbd6fdf6921d50d24f5baf`;
  the retained rollback image is
  `sha256:a1a8a2b9ddfcbb8acde07b6b8313d9285481c4aa18a465275b7d1eb6266ddc46`.
- Runtime inspection confirms `TaskMutationService.execute_governed` is
  installed, `DiscordTasksSurface` delegates to governed execution, no direct
  task adapter create/update/delete call remains there, and the bot shares one
  Governor operation store across Brain tools and task surfaces.
- Docker reports healthy with zero restarts. Discord reconnected, restored its
  persistent views, and initialized startup surfaces without an application
  error. The optional PyNaCl/davey voice-support warnings are unchanged and do
  not affect text operations.
- Health reports Discord ready and Brain tools enabled. Direct task and
  supplies surfaces remain disabled, and due-notification messages remain
  disabled as configured; no retired channel was re-enabled for testing.
- PostgreSQL retained all three earlier operations as completed and contains
  zero pending durable payloads after deployment.
- H4 doctor reports Governor reachability, Discord readiness, and Brain tools
  enabled. The normal post-deployment approved-task evidence and its terminal
  response replay are recorded below.

Slice 2 observation incident and correction (2026-08-30):

- The normal observation task `테스트 관찰` was created successfully and
  exists exactly once in the authoritative calendar with UID
  `30791be8-aff0-4546-abcf-092269590145`. PostgreSQL records the operation as
  completed, its confirmation as approved once, all four lifecycle audit
  events, and zero pending payloads.
- H4 nevertheless rendered a failure 1.6 seconds after completion because a
  repeated approval delivery reached the endpoint after correct terminal
  payload cleanup. The endpoint looked for the deleted pending payload before
  recognizing the already-completed operation and returned
  `operation_payload_not_found`.
- The approval endpoint now returns a sanitized completed receipt for a
  repeated delivery by the same actor without executing the domain mutation
  again or retaining raw memo content. A different actor remains rejected.
  The replay behavior covers task, event, memo, and Paperless confirmation
  receipts.
- Local correction validation passed 78 focused approval/tool tests, all 221
  Governor tests with 10 PostgreSQL-only tests skipped in this unit run, and
  the full 352-test Discord suite.
- Commit `53d8996` was deployed through the guarded H3 restart. The preceding
  healthy image is retained as
  `kaosgdd-ai-governor-discord:rollback-f6b8257` with image ID
  `sha256:8ea38f0687593f46b7e3c3d00854897343fb0125edfbd6fdf6921d50d24f5baf`.
  The corrected running image is
  `sha256:d3d421dc9f46e69515b9fb0a6d354ce4de89085a2b147365e4be05c4b844dc40`.
- Replaying the exact completed production confirmation returned HTTP success,
  `status=completed`, `replayed=true`, and the original authoritative task UID.
  The operation count remained four completed, the observed operation retained
  exactly four audit records, and the pending-payload count remained zero, so
  the replay performed no second domain write or lifecycle transition.
- The corrected H3 container is healthy with zero restarts; Discord startup is
  complete, direct task/supplies surfaces remain inactive, and H4 doctor
  reports Governor, Discord, and Brain tools reachable. This closes slice 2's
  production observation gate.

Memos slice 1 implemented and deployed:

- Added transport-neutral `MemoMutationCommand`, `MemoMutationService`, and a
  narrow Memos mutation adapter protocol under the Governor Memos domain.
- Registered deterministic `create`, `edit`, and `delete` handlers. The
  boundary validates required content, exact `memos/<id>` names, maximum
  content length, and authoritative adapter result-name consistency.
- Added explicit governed execution for later deterministic callers. Durable
  operation parameters contain the memo name plus content SHA-256 and byte
  length, never the raw memo body; replay returns the completed durable result
  without a second Memos write.
- Shared one `MemoMutationService` instance from the H3 bot and routed the
  existing confirmed Brain/iOS create/edit/delete path through it. Proposal,
  confirmation, actor/scope, response payload, terminal payload cleanup, and
  Memos error behavior remain compatible.
- Kept the active `DiscordMemosCapture` create/edit/delete writer unchanged for
  a separately deployable slice 2. Search and read operations remain direct
  Memos domain reads and do not require Governor mutation records.

Memos slice 1 files:

- `apps/governor/src/kaos_governor/memos/mutations.py`
- `apps/governor/src/kaos_governor/memos/__init__.py`
- `apps/governor/tests/test_memo_mutations.py`
- `apps/governor/tests/test_postgres_durable.py`
- `integrations/discord/src/kaos_governor_discord/bot.py`
- `integrations/discord/src/kaos_governor_discord/tools.py`

Memos slice 1 validation:

- 9 focused memo mutation domain tests and 78 Brain tool/approval tests passed.
- All 231 Governor tests passed with 11 PostgreSQL-gated tests skipped in the
  unit run; all 11 then passed against isolated PostgreSQL 16, including memo
  governed-execution durability and replay.
- All 352 Discord and 321 Brain regression tests passed.
- Container package build/compilation and `git diff --check` passed.

Memos slice 1 production gate:

- [x] Handler validation and adapter contract tests
- [x] Confirmed create/edit/delete transport parity
- [x] Durable memory and PostgreSQL execution/replay tests
- [x] Governor, Discord, and Brain regression suites
- [x] Review and commit
- [x] Controlled H3 deployment
- [x] Reconcile a normal confirmed memo with Memos and Governor audit state
- [x] Slice observation gate

Memos slice 1 production promotion evidence (2026-08-30):

- Commit `1e6a3aa` was deployed through the guarded H3 restart. The preceding
  task-slice image is retained as
  `kaosgdd-ai-governor-discord:rollback-7521ac0` with image ID
  `sha256:d3d421dc9f46e69515b9fb0a6d354ce4de89085a2b147365e4be05c4b844dc40`.
  The running Memos handler image is
  `sha256:ebbe0fe15f8116f4fa149b5d3f6d99a9672998a5ab5f22d42dd91b6effaf9275`.
- Installed runtime inspection confirms all three memo handlers, confirmed
  route delegation to `MemoMutationService`, no direct Memos create/update/
  delete call in the confirmation handler, and one shared handler owned by the
  bot.
- Docker is healthy with zero restarts. Discord reconnected, restored its
  persistent views, and completed startup initialization; Memos reports healthy
  and configured. The direct memo-capture surface remains enabled on its
  unchanged writer.
- All four preceding durable operations remain completed and the pending
  payload table remains empty. H4 doctor reports Governor reachability,
  Discord readiness, and Brain tools enabled.
- One normal confirmed Brain memo and authoritative Memos/audit reconciliation
  completed on 2026-08-30. Operation
  `op_1f205a716d8b0ef61cd143d8890d83c3` completed once and returned
  `memos/LZ44eThP6c4NjmWCK8s2AK`. The authoritative private memo contains the
  exact 42-byte observation text, exact-content search returns one memo, four
  ordered lifecycle audit records are present, and the pending-payload count is
  zero. This closes Memos slice 1's production observation gate.

Risk: low to medium. This changes only final dispatch after the existing
confirmation has been approved. The direct capture UI remains on its current
writer until this slice has production evidence.

Rollback: recreate the preceding H3 Governor/Discord image. The handler adds
no schema and does not change authoritative Memos data or credentials.

Memos slice 2 scope (started 2026-08-30):

- Route direct Discord Memos create, edit, delete, and undo-create actions
  through `MemoMutationService.execute_governed` and the bot's shared durable
  `GovernorOperations` store.
- Derive the personal user actor and idempotency key from the Discord message
  or interaction. Retried delivery of the same explicit action must not repeat
  an authoritative Memos write.
- Preserve the existing `+++` capture marker, modal and confirmation UX,
  message cleanup, and response copy. Search, browse, and open remain direct
  read-only Memos domain operations.
- Keep memo content out of durable operation parameters; retain only the
  existing content fingerprint and byte length.

Memos slice 2 expected files:

- `integrations/discord/src/kaos_governor_discord/memos.py`
- `integrations/discord/src/kaos_governor_discord/bot.py`
- `integrations/discord/tests/test_memos.py`
- narrow Governor memo result changes and tests only if required to return the
  authoritative adapter record without a second upstream read

Risk: medium around Discord interaction retries, undo behavior, and avoiding a
false UI failure after a successful authoritative write.

Rollback: restore `DiscordMemosCapture` construction and its three mutation
methods to direct `MemosService` calls. No schema or Memos data migration is in
scope.

Memos slice 2 implementation and validation:

- `DiscordMemosCapture` now owns no direct create, update, or delete adapter
  dispatch. All four explicit mutation entry points (`+++`, add modal,
  edit/delete controls, and undo delete) execute through the shared
  `MemoMutationService` and PostgreSQL-backed `GovernorOperations` instance.
- Discord message and interaction IDs provide stable idempotency keys and the
  authenticated Discord user becomes the personal Governor actor. A system
  actor and random key are retained only for internal/test callers without a
  Discord context.
- Create and edit return the authoritative adapter record from the successful
  handler execution. This avoids a second upstream read and therefore avoids a
  false UI failure after a committed Memos write. A replay may read the named
  memo to reconstruct the UI, but never repeats the write.
- Durable parameters continue to contain only memo name, content SHA-256, and
  byte length. Search/read paths and existing Discord copy and controls are
  unchanged.
- 24 focused Discord Memos tests, all 231 Governor tests (11 PostgreSQL tests
  gated in that run), all 11 isolated PostgreSQL 16 integration tests, all 355
  Discord tests, and all 321 Brain tests passed. Package compilation,
  container builds, and `git diff --check` passed.

Memos slice 2 production gate:

- [x] Direct create/edit/delete and replay tests
- [x] Actor, idempotency, content-redaction, and authoritative-result tests
- [x] Governor, PostgreSQL, Discord, and Brain regression suites
- [ ] Review and commit
- [ ] Controlled H3 deployment
- [ ] Reconcile one direct Discord memo capture with Memos and Governor audit
- [ ] Slice observation gate

H4 task-create routing correction:

- A normal observation attempt, `전염병신고 할일 만들어줘`, incorrectly
  returned the active-task list because the deterministic task-create parser
  recognized `추가`/`저장`/`등록` but not `만들어`/`생성`.
- The parser now recognizes common polite forms of both verbs, and the
  read-only tool router treats them as mutation language so it cannot fall
  through to an active-task lookup.
- Exact parser, tool-routing, and end-to-end bot regressions verify that the
  request proposes task creation, performs no active-list fetch, and still
  requires Governor confirmation.
- Full Brain regression: 321 tests passed. H4 was promoted to `99011fb`; the
  deployed parser resolves the reported phrase to title `전염병신고` with no
  read-only route. Systemd, container, Discord gateway, and dependency checks
  are healthy with zero container restarts. The prior H4 image remains tagged
  `kaos-brain:rollback-e7e416f`. H3 remains unchanged.

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

Deferred mobile interaction:

- Add a read-only `Open Memo` action to the Memos Shortcut after the initial
  list/search workflow is stable.
- Build the target from the authoritative Memos resource name by removing the
  `memos/` prefix and opening
  `https://memos.kaosgdd.net/m/{memo-id}`. Do not introduce a second memo ID or
  a Kaos redirect endpoint solely for this action.
- Treat this as an exact-memo web deep link, not a guaranteed launch into the
  installed Home Screen PWA. iOS currently opens externally invoked HTTPS
  links from Shortcuts in the browser because installed web apps cannot
  reliably capture in-scope links. Re-test this behavior on the target iOS
  version before implementation.
- Keep the first version read-only. Memo editing and deletion remain separate
  Governor-controlled actions with the normal validation and confirmation
  policy.

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
| 2026-08-30 | 1-2 | Promoted commit `11b18be`, migration 005, and the PostgreSQL-backed Discord operation store after pre/post recovery exercises | Both custom-format backups restored into isolated PostgreSQL 16; live proposal/approval/completion/audit/payload cleanup passed; API, Discord, and PostgreSQL healthy with zero restarts | Production observation started; compatibility and memory-store rollback path retained |
| 2026-08-30 | 3 | Extracted the first task/supplies execution slice from the Discord HTTP adapter into registered Governor task handlers | 8 focused task tests; 208 Governor unit/contract + 9 PostgreSQL integration + 349 Discord + 317 Brain tests passed | None; code is locally validated and Phase 2 observation remains open |
| 2026-08-30 | 3 | Corrected Korean `만들어`/`생성` task-create routing discovered during normal H4 observation | Exact parser/tool/bot regressions and all 321 Brain tests passed; deployed runtime parses the reported phrase as task `전염병신고` without a read-only lookup | H4 Brain deployed at `99011fb`, healthy with zero restarts; prior image tagged for rollback; H3 unchanged |
| 2026-08-30 | 1-2 | Completed the production observation gate with a normal user-approved task creation | Durable operation completed; confirmation approved once; four lifecycle audit events present; pending payload removed; live calendar task UID matched the operation result | Phases 1 and 2 complete; Phase 3 slice 1 is eligible for controlled H3 deployment |
| 2026-08-30 | 3 | Promoted the task-handler slice to H3 through the guarded Discord/Governor restart | New handler present and wired; container healthy with zero restarts; Discord ready; H4 dependency checks pass; durable operations retained with zero pending payloads | Production observation started; rollback image `kaosgdd-ai-governor-discord:rollback-11b18be` retained |
| 2026-08-30 | 3 | Completed task-handler slice 1 production observation | Post-deployment task completed through the handler; confirmation approved once; four audit events present; payload removed; authoritative calendar UID matched the operation result; zero restarts | Slice 1 complete; direct Discord task/supplies writers remain the next task slice |
| 2026-08-30 | 3 | Routed direct Discord task/supplies writes through shared governed task execution | 11 focused Governor + 59 task-surface tests; 221 Governor discovered with all 10 PostgreSQL tests passed separately; 351 Discord + 321 Brain tests passed | None; slice 2 validated locally, production direct surfaces remain disabled |
| 2026-08-30 | 3 | Promoted direct Discord task/supplies governed execution to H3 | Commit `1b9405a`; installed-path inspection confirms governed delegation and shared durable store; container healthy with zero restarts; Discord and H4 dependencies ready; 3 completed operations retained and 0 pending payloads | Slice 2 production observation started; direct task/supplies surfaces remain disabled; rollback image `kaosgdd-ai-governor-discord:rollback-1cc96e1` retained |
| 2026-08-30 | 3 | Diagnosed a false Discord failure after the slice 2 observation task had completed | Operation completed once and authoritative UID matched; a repeated approval hit correct payload cleanup and received `operation_payload_not_found`; idempotent terminal receipt tests pass for the same actor while another actor is rejected | Task data is correct; approval-replay correction validated locally and awaiting H3 promotion |
| 2026-08-30 | 3 | Promoted the approval-replay correction and closed task slice 2 observation | Exact completed confirmation replay returned the original UID with no second write; 4 completed operations and 0 payloads retained; container healthy with zero restarts; Discord and H4 dependencies ready | Task slices 1 and 2 complete; rollback image `kaosgdd-ai-governor-discord:rollback-f6b8257` retained; Memos is next |
| 2026-08-30 | 3 | Added the Governor Memos handler and routed confirmed Brain/iOS memo mutations through it | 9 focused memo + 78 tool tests; 231 Governor with all 11 PostgreSQL tests passed separately; 352 Discord + 321 Brain tests passed | None; Memos slice 1 validated locally, direct Discord capture writer unchanged |
| 2026-08-30 | 3 | Promoted Memos handler slice 1 to H3 | Commit `1e6a3aa`; installed route delegates to the shared handler with no direct confirmation write; container healthy with zero restarts; 4 completed operations retained and 0 pending payloads; H4 dependencies ready | Production observation started; direct memo-capture writer unchanged; rollback image `kaosgdd-ai-governor-discord:rollback-7521ac0` retained |
| 2026-08-30 | 3 | Completed Memos handler slice 1 production observation | Normal Brain confirmation created authoritative memo `memos/LZ44eThP6c4NjmWCK8s2AK`; exact content count 1; operation completed with four ordered audit records and zero pending payloads; container healthy with zero restarts | Slice 1 complete; direct Discord Memos capture remains the next slice |
| 2026-08-30 | 3 | Started Memos slice 2 for direct Discord mutation routing | Scope records shared durable operations, Discord actor/idempotency derivation, unchanged read paths and UX, and no raw memo content in the ledger | None; implementation started |
| 2026-08-30 | 3 | Routed direct Discord Memos mutations through the shared Governor lifecycle | 24 focused Memos + 231 Governor + 11 isolated PostgreSQL + 355 Discord + 321 Brain tests passed; authoritative result prevents a post-write read failure; retries do not repeat writes | None; locally validated and awaiting review/commit |
| 2026-08-30 | 6 | Recorded deferred Shortcut deep-link support for opening a selected Memos item | Existing Memos route and ID mapping verified as `/m/{memo-id}`; iOS external-link/PWA limitation documented | None; planning only |

## How to Update This Tracker

For every implementation turn:

1. Mark the phase **In progress** before broad code changes.
2. Record the exact scope and any changed assumptions.
3. Update the affected-files, risk, tests, and rollback sections.
4. Record test counts and production impact in the progress log.
5. Distinguish local validation, commit, deployment, and observation; do not
   call a phase complete merely because code exists.
6. Never mark a production gate complete without direct evidence.
