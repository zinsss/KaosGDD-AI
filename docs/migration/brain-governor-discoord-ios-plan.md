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
  route on 2026-08-30. Direct Discord Memos capture slice 2 was deployed on
  2026-08-30 and is under production observation.
- H4 Brain correction: Korean task-create requests using `만들어` or `생성`
  were corrected and deployed in commit `99011fb` on 2026-08-30. This was an
  intent parser deployment only and did not promote the Phase 3 Governor
  handler slice on H3.
- Phase 1 was committed and deployed with Phase 2 in commit `11b18be`.
- Production behavior: Governor/Discord uses the PostgreSQL operation store;
  public HTTP and Discord behavior remains compatible.
- Architecture decision: Discord's final role is the single private `#brain`
  topic. Direct operational channels are now compatibility surfaces scheduled
  for gated retirement; see
  [Discord Brain-Only Target](../architecture/discord-brain-only.md).
- Interface decision: retain the existing personal KaosGDD PWA as the primary
  visual console and use Shortcuts for Action Button, Siri, Share Sheet,
  quick-action, and deep-link integration. Native Calendar/Reminders remain
  Radicale sync and notification clients rather than mandatory daily UIs; see
  [Personal KaosGDD PWA and iOS Shortcuts](../architecture/personal-pwa-shortcuts.md).
- Brain direction: `#brain` remains a natural-language KaosGDD gateway and may
  grow into a conversational system-operations console. Brain never becomes a
  privileged runner; Governor and restricted host executors own typed,
  confirmed, audited runbooks. See [Brain as Kaos Gateway and System
  Operator](../architecture/brain-system-operations.md).
- Phase 5 started with the Governor-side Discord adapter package extraction.
  Commit `20732fa` is deployed on H3: the canonical package/path is
  `kaosdiscoord` under `integrations/discoord`, while legacy imports and the
  current H3 deployment identity remain compatibility shims during
  observation.
- Phase 5 worker slice 2 is deployed in commit `356e1b4`: Pushover delivery is
  owned by the independent `kaos-governor-worker`; KaosDiscoord is queue-only.
- Phase 5 worker slice 3 completed production observation on 2026-08-31: the
  organic 07:00 `Good Morning.` notification was scheduled by the worker,
  delivered through the Pushover outbox, and confirmed received by the user.
- Phase 5 worker slice 4 is deployed in commit `3d98e40`: Naver mail and fax
  polling are owned by `kaos-governor-worker` without uploading messages or
  attachments to Discord. Organic mail/fax observation is active.
- Phase 6 slice 1 is deployed in commit `0d9448a`: the shared personal/family
  PWA accepts a real `#/calendar?date=YYYY-MM-DD` deep link for Shortcuts,
  ignores invalid dates, and performs no backend operation. Both host profiles
  serve the committed helper and the portal retained zero restarts.
- Phase 6 slice 2 is deployed in commit `216d1ba`: the personal profile uses
  one native selector for Agenda, Calendar, Tasks, Memos, Documents, Fax, Mail,
  Utils, and Settings. Family navigation is unchanged; Fax and Mail are honest
  transitional routes rather than false working controls.
- Phase 6 slice 3 is deployed in commit `e0a7ac9`: the existing
  Kaos Memos client now runs locally for the personal route, and Documents is a
  KaosGDD-owned read-only Paperless browser. Normal user UI observation is
  pending before the slice is closed.
- Database schema in production: additive migration `005`.
- Working rule: finish and verify one boundary before moving another domain.

## Progress

| Phase | Objective | Implementation | Production | Status |
| --- | --- | --- | --- | --- |
| 0 | Audit current architecture and flows | Complete | No change | Complete |
| 1 | Establish the Governor operation boundary | Complete and tested | Deployed and observed 2026-08-30 | Complete |
| 2 | Persist operations, confirmations, and pending payloads | Complete and tested | Deployed and observed 2026-08-30 | Complete |
| 3 | Route every meaningful mutation through Governor | Task slices and Memos slices 1-2 implemented | Task slices and Memos slice 1 observed; Memos slice 2 deployed 2026-08-30 | Production observation |
| 4 | Make Brain transport-neutral | Not started | Not deployed | Planned |
| 5 | Retain brain-only KaosDiscoord; detach workers and notifications | Package, Pushover, digest, and fax/mail worker slices implemented | Pushover and digest observed; fax/mail observation active | In progress |
| 6 | Retain the personal PWA and add stable iOS integrations | Deep link, compact menu, personal Memos repair, Paperless browser, and Archive Terminal slice implemented | UI slices deployed; Memos/Paperless/Fax authenticated observation active | In progress |
| 7 | Remove compatibility debt and finish documentation/CI | Not started | Not deployed | Planned |
| 8 | Add governed Brain system operations | Architecture accepted; current Guard remains deny-by-default | Not deployed | Planned |

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
Discord #brain ──> KaosDiscoord ──> KaosBrain ──> KaosGovernor

Personal/Family PWAs / Shortcuts / optional Scriptable ─> KaosGovernor
                                      Ask Kaos ─> KaosBrain ─> KaosGovernor

KaosGovernor ──> notification outbox ──> Pushover

KaosGovernor ──> domain services/adapters ──> authoritative services
                                            Radicale / Memos / Paperless / HylaFAX
```

Ownership rules:

1. Brain interprets, reasons, answers, and proposes structured actions.
2. Governor deterministically validates, authorizes, confirms, routes, and
   records operations.
3. Discoord transports the retained `#brain` conversation and owns no domain
   policy. Direct operational Discord surfaces are transitional.
4. Domain services execute and preserve their existing sources of truth.
5. Personal/Family PWAs, Shortcuts, and Scriptable are clients, not state
   stores. Scriptable is optional rather than a required calendar container.
6. Notifications are Governor/domain behavior. Pushover is the target
   immediate text adapter; native iOS apps own task/calendar reminders.
7. Deterministic callers do not invoke an LLM.

## Preserved Constraints

- No unnecessary microservices or container split.
- No Radicale, Memos, Paperless, HylaFAX, PACS, or DICOM rewrite.
- No change to the HylaFAX spool, modem, services, or documented
  `setup.cache`/`setup.modem` workaround.
- No second task, memo, calendar, or supplies state store for iOS.
- No duplicated personal calendar/task implementation inside Scriptable when
  the existing PWA can provide the visual surface.
- No broad Governor bearer token stored on an iPhone.
- No API duplication for Discord and iOS.
- No removal of compatibility routes or Discord channels before replacement
  parity, observation, and an explicit history retain/export decision.
- Database changes are additive and rollback-aware.
- H4 retains the conversational bot and `#brain`. H3's operational Discord
  identity remains only until Governor workers and direct-channel replacements
  are independently verified.

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
- `integrations/discoord/src/kaosdiscoord/tools.py`
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
- `integrations/discoord/src/kaosdiscoord/config.py`
- `integrations/discoord/src/kaosdiscoord/main.py`
- `integrations/discoord/src/kaosdiscoord/tools.py`
- `integrations/discoord/tests/test_tools.py`
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
- `integrations/discoord/src/kaosdiscoord/tools.py`

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
- `integrations/discoord/src/kaosdiscoord/bot.py`
- `integrations/discoord/src/kaosdiscoord/tasks.py`
- `integrations/discoord/tests/test_tasks.py`

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
- `integrations/discoord/src/kaosdiscoord/bot.py`
- `integrations/discoord/src/kaosdiscoord/tools.py`

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

- `integrations/discoord/src/kaosdiscoord/memos.py`
- `integrations/discoord/src/kaosdiscoord/bot.py`
- `integrations/discoord/tests/test_memos.py`
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
- [x] Review and commit (`7c9f577`)
- [x] Controlled H3 deployment
- [ ] Reconcile one direct Discord memo capture with Memos and Governor audit
  (not required solely for migration after the brain-only decision)
- [x] Record the slice as deployed compatibility hardening; do not solicit a
  new direct-channel write before retirement

Memos slice 2 production promotion evidence (2026-08-30):

- Commit `7c9f577` was deployed through the guarded H3 restart. The fully
  observed slice-1 image is retained as
  `kaosgdd-ai-governor-discord:rollback-1e6a3aa` with image ID
  `sha256:ebbe0fe15f8116f4fa149b5d3f6d99a9672998a5ab5f22d42dd91b6effaf9275`.
  The running slice-2 image is
  `sha256:e64429338e2aafa30005efaf1adea0dff2a093cab1e47e7ec69f5f309c001524`.
- Installed runtime inspection confirms governed create/edit/delete dispatch
  and injection of the bot's shared `GovernorOperations` and
  `MemoMutationService` objects.
- The container is healthy with zero restarts; Discord is ready and startup
  surfaces initialized. Memos, Paperless, fax, mail, Pushover, and all service
  checks remain healthy/configured.
- All five preceding durable operations remain completed and the pending
  payload table remains empty. H4 doctor reports Brain, Governor, Discord, and
  Brain tools healthy; the H4 checkout is fast-forwarded to `23953b5`.
- A normal direct `+++` capture was not solicited after the accepted decision
  to retire every Discord surface except `#brain`. The governed path remains
  deployed as compatibility hardening while the channel exists, but no further
  product work depends on this direct surface.

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

- `integrations/discoord/src/kaosdiscoord/tasks.py`, Memos, inbox, fax, mail,
  and organizer paths
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

## Phase 5 — Brain-Only KaosDiscoord and Independent Workers

Status: planned.

Objective:

- Retain Discord only for the H4 `#brain` conversation, and make Governor
  workers plus immediate Pushover delivery independent of every Discord
  gateway lifecycle.

Planned implementation:

- Freeze feature development for direct Discord task, calendar, supplies,
  Memos, document, mail/fax, notification, alert, and administration channels.
- Keep the H4 `#brain` adapter narrow: conversation, Brain answers, structured
  proposals, confirmations, requested files, and operation receipts.
- Inventory every H3 operational-bot worker. Move Pushover delivery, daily
  digest, maintenance checks, mail/fax polling, schedulers, health/tool routes,
  and domain adapters behind a Governor-owned runtime entry point before
  disconnecting the H3 Discord gateway.
- Preserve current modular-monolith deployment unless process separation is
  operationally required.
- Disable direct channel intake one domain at a time only after the Phase 6
  replacement passes production observation.
- Export or deliberately retain required Discord history before channel
  deletion. Discord must not remain the sole mail/fax/document archive.
- Preserve simple Apple Watch copy and native iOS task/calendar notifications.

Phase 5 slice 1 — Governor-side KaosDiscoord package boundary:

- Move `integrations/discord` to `integrations/discoord` and make
  `kaosdiscoord` the canonical Python package, distribution, imports, tests,
  and console entry point.
- Move all H3 Discord-specific actions, views, formatters, channel/user IDs,
  attachments, interactions, and presentation code with that package. Do not
  move Governor domain services or deterministic policies into it.
- Retain a thin `kaos_governor_discord` import/console compatibility layer for
  one observation period. It may re-export KaosDiscoord symbols but must not
  contain a second implementation.
- Keep the current Compose service, container, image name, data mounts,
  credentials, ports, and production behavior unchanged in this slice. Runtime
  identity changes occur only after imports and operations are observed.
- Add compatibility tests proving old and new imports resolve to the same
  implementation, plus dependency tests preventing `kaosdiscoord` imports in
  Governor.

Phase 5 slice 1 expected files:

- `integrations/discoord/pyproject.toml`
- `integrations/discoord/Dockerfile`
- `integrations/discoord/src/kaosdiscoord/`
- `integrations/discoord/src/kaos_governor_discord/` compatibility shims
- `integrations/discoord/tests/`
- H3 Compose/build path references and architecture/operations documentation

Risk: medium around Python module identity, console entry points, Docker build
paths, and hidden operational imports. No Discord behavior or channel should
change.

Rollback: restore the previous directory/package path and the retained
`kaos-governor-discord` console entry point. No database, state, channel, or
credential migration is involved.

Slice 1 local validation (2026-08-30):

- canonical `kaosdiscoord` and compatibility `kaos-governor-discord` console
  entry points are both installed and resolve to version `0.6.0`
- legacy module imports resolve to canonical implementation classes
- the dependency boundary test confirms Governor contains no Discord,
  `kaosdiscoord`, or `kaos_governor_discord` imports
- 231 Governor + 358 KaosDiscoord + 321 Brain tests passed
- H3 preflight and Compose rendering passed

Slice 1 production deployment (2026-08-30):

- commit `20732fa` was pushed to `main` and synced to H4
- H3 runs canonical entry point `kaosdiscoord` inside the unchanged
  `kaos-governor-discord` service/container identity
- installed canonical and legacy imports resolve to the same implementation
- container is healthy and Discord-ready with zero restarts
- the durable ledger remained at 5 completed operations and 0 pending payloads
- H4 doctor passes at the same commit with Governor and Discord dependencies
  ready
- rollback image `kaosgdd-ai-governor-discord:rollback-pre-kaosdiscoord`
  retains image `sha256:e64429338e2aafa30005efaf1adea0dff2a093cab1e47e7ec69f5f309c001524`

Compatibility observation has started. The wider Phase 5 worker detachment
remains in progress.

Phase 5 slice 2 — independent Pushover delivery worker:

- Inventory every `GovernorBot` lifecycle and record its Discord dependency in
  [H3 Worker Detachment](../architecture/h3-worker-detachment.md).
- Add `kaos-governor-worker` as a Governor-owned process with its own image,
  health check, and notification-state mount.
- Add `PUSHOVER_DELIVERY_MODE=inline|worker`. In worker mode, KaosDiscoord
  producers queue notifications but never deliver them.
- Protect the shared JSON outbox with a cross-process lock and retain existing
  notification keys/deduplication records.
- Start the worker and switch KaosDiscoord to queue-only in the same guarded
  Compose deployment. Never run both delivery owners.
- Do not move digest, mail, fax, maintenance, health/tool, or direct Discord
  loops in this slice; their Discord callbacks require separate replacement
  work.

Risk: medium around shared-file concurrency and duplicate Pushover delivery.
Tests must prove queue-only behavior, worker-only delivery, stale health
detection, and compatibility with inline rollback mode.

Rollback: stop `governor-worker`, restore inline mode, and recreate the retained
KaosDiscoord image. Both paths use the same outbox and delivered-key history.

Slice 2 local validation (2026-08-30):

- 237 Governor + 359 KaosDiscoord + 321 Brain tests passed
- two independent concurrent producers retained all 40 test outbox records
- queue-only mode performs no inline Pushover call, while the worker drains the
  same outbox and preserves delivered-key deduplication
- missing, stale, and degraded worker heartbeats fail health checks
- the dedicated read-only worker image started with the canonical
  `kaos-governor-worker` entry point and became healthy
- H3 preflight, Bash validation, and Compose rendering passed

Slice 2 production deployment (2026-08-30):

- commit `356e1b4` was pushed to `main` and synced to H4
- the guarded cutover built both images, stopped the old inline owner, started
  and health-checked `kaos-governor-worker`, then started KaosDiscoord in
  queue-only mode
- worker and KaosDiscoord are healthy with zero restarts; H4 doctor passes
- KaosDiscoord reports `deliveryMode=worker`, `deliveryOwner=governor-worker`,
  and a five-second poll
- the existing Pushover outbox remained at 0 pending and 7 delivered records
  with no error; the worker heartbeat is ready and current
- the durable Governor ledger remained at 5 completed operations and 0 pending
  payloads
- rollback image `kaosgdd-ai-governor-discord:rollback-pre-pushover-worker`
  retains image `sha256:9175013d0926db3b969ed2adcd3cbcffbb8c15d50197d69175a7f6773d21a74c`

Slice 2 production observation completed on 2026-08-30 with an organic
incoming fax. HylaFAX finished the one-page receipt at 16:49:18 KST; H3
archived it at 16:50:26 KST, KaosDiscoord queued the keyed `Fax received.`
record, and `kaos-governor-worker` delivered it at 16:50:27 KST. The shared
outbox advanced from 7 to 8 delivered records with 0 pending, retained one
fax key, and both containers remained healthy with zero restarts. No synthetic
watch alert was needed.

Phase 5 slice 3 — worker-owned daily-digest schedule and alert priority:

- Add durable per-notification priority to the shared Pushover outbox. Routine
  information is priority `0`; actionable failures and required intervention
  are priority `1`.
- Add `DAILY_DIGEST_OWNER=discord|worker` with `discord` as the compatibility
  default and `worker` as the H3 target.
- Move initialization, due-time checking, live aggregate construction,
  content refresh, and morning/event Pushover enqueueing into
  `kaos-governor-worker`.
- Persist the rendered digest as a locked pending publication. KaosDiscoord
  temporarily transports that publication with the existing controls, but no
  longer makes scheduling decisions or queues duplicate Watch alerts.
- Keep the same daily-digest state and content cache. A same-day owner cutover
  must honor `lastSentDate` and never duplicate a digest.

Slice 3 local validation (2026-08-30):

- 240 Governor + 361 KaosDiscoord tests passed
- normal/high priority survives queue persistence and worker delivery
- priority policy tests cover daily, mail, fax success/receipt/failure,
  service down/recovery, maintenance, and authentication renewal
- two `DailyDigestService` instances share the locked schedule/publication
  state, proving worker-to-transport restart continuity
- worker tests prove one normal-priority morning record plus one record per
  event, followed by delivery through the existing sole Pushover owner
- KaosDiscoord tests prove worker-owned mode only transports a pending rendered
  publication and retains Weather/Bible/Quote/Close controls
- H3 Bash validation, preflight, and Compose rendering passed

Risk: medium around the 07:00 owner boundary and cross-process publication
state. Rollback sets `DAILY_DIGEST_OWNER=discord`, recreates the worker and
KaosDiscoord with the retained images, and preserves the same digest/cache and
Pushover state files.

Slice 3 production deployment (2026-08-30):

- commit `58e5237` was pushed to `main` and synced to H4
- H3 now runs `DAILY_DIGEST_OWNER=worker` and Pushover compatibility fallback
  priority `0`; both installed processes report the same ownership
- the guarded sequence retained the old KaosDiscoord and worker images, stopped
  the old scheduler first, started and health-checked the worker owner, then
  restored KaosDiscoord as publication transport
- the existing `lastSentDate=2026-08-30` was preserved, so the after-07:00
  cutover produced no duplicate digest or Watch message
- worker status reports owner `worker`, 0 pending publications, 0 scheduled
  notifications in the cutover cycle, and no error
- Pushover remained at 0 pending and 8 delivered records with no error
- worker and KaosDiscoord are healthy with zero restarts; the H4 doctor passes
  all Brain, Governor, Discord, and tool checks at the same commit
- rollback images are
  `kaosgdd-ai-governor-discord:rollback-pre-digest-worker` at
  `sha256:997898c57dbf62de49770b14a0a675ca226660caaf2c60ef9bad6f468cb2caa2`
  and `kaosgdd-ai-governor-worker:rollback-pre-digest-worker` at
  `sha256:b2d4f81e794f4c416ad7581106ed20e48651795e553d53526c9ac0c5d0144446`

Slice 3 production observation completed on 2026-08-31. The worker scheduled
the organic `Good Morning.` digest at `07:00:12 KST`, persisted status `sent`
with no error or pending publication, and recorded the corresponding
KaosDiscoord publication. The Pushover worker delivered the ninth outbox record
at `07:00:13 KST` with 0 pending and no error. The user confirmed receipt;
worker and KaosDiscoord remained healthy with zero restarts. No synthetic alert
was required.

Phase 5 slice 4 — worker-owned Naver mail and fax polling:

- Add `MAIL_NAVER_OWNER=discord|worker` and
  `FAX_LIFECYCLE_OWNER=discord|worker`, preserving `discord` as the code
  rollback default and selecting `worker` only during the guarded H3 cutover.
- Move IMAP checkpoint advancement, fax connector reconciliation, incoming fax
  PDF retention, and final fax/mail Pushover production into
  `kaos-governor-worker`.
- Keep Naver IMAP authoritative for message bodies and attachments. The worker
  queues one normal-priority `Mail received.` record per new message and does
  not create a Discord or second local attachment archive.
- Keep incoming fax PDFs in the existing H3 fax archive used by the H4
  `Fax Mail` selector. Queue only `Fax received.` and `Fax sent.` at normal
  priority and `Fax send failed.` at high priority; queued/sending states stay
  silent.
- Add a cross-process fax state lock because transitional Discord fax intake
  can still submit a job while the worker reconciles it.
- Retain only adapter-specific cleanup in KaosDiscoord so a successful fax can
  delete its transitional Discord source message. KaosDiscoord performs no
  connector polling, fax archival, status notification, or mail upload when
  worker ownership is selected.
- Persist mail/fax runtime status in their existing state files so the H3
  readiness and Brain import views can observe the worker-owned lifecycle
  across process boundaries.

Slice 4 local validation (2026-08-30):

- focused tests prove one owner, final-state-only fax alerts, normal/high
  priority policy, Naver IMAP retention, no Discord attachment callback, and
  adapter-only fax source cleanup
- 250 Governor tests passed with 11 PostgreSQL tests skipped in the unit image
- 368 KaosDiscoord and 321 KaosBrain tests passed
- H3 Bash validation, preflight, and Compose rendering passed
- the worker runtime image contains `tiff2pdf` for local-transport rollback and
  imports both neutral lifecycle workers successfully

Slice 4 production deployment (2026-08-30):

- commit `3d98e40` was pushed to `main` and synchronized to H4
- H3 now runs `MAIL_NAVER_OWNER=worker` and
  `FAX_LIFECYCLE_OWNER=worker` in both installed processes
- the guarded sequence retained both old images and copied mail, fax, and
  Pushover state before stopping KaosDiscoord, recreating the worker owner,
  health-checking it, and restoring KaosDiscoord as intake/cleanup transport
- the Naver checkpoint retained 2 mailboxes and advanced from
  `2026-08-30T11:04:46Z` to `2026-08-30T11:05:47Z` under the worker with no
  error or new mail
- fax state retained 3 incoming records, 4 jobs, and 53 delivered actions; its
  scan timestamp advanced under the worker with no connector error
- Pushover remained at 0 pending and 8 delivered records, proving the owner
  change emitted no duplicate or synthetic Watch alert
- authenticated Brain routes still return HTTP 200 for recent imports and live
  Naver mail; H4 doctor passes all Brain, Governor, Discord, and tool checks
- worker image `0.3.0` and KaosDiscoord are healthy with zero restarts; their
  deployed image IDs are
  `sha256:7c46f857222ba1804b8764747b4c53a35a71a7c45318f6f56fb2f06494716133`
  and
  `sha256:bb56cafe98b790350deb238a05c6246cc0cbf6f408a6bba96dd6faf67ffa60fc`
- rollback images are
  `kaosgdd-ai-governor-worker:rollback-pre-fax-mail-worker` at
  `sha256:b282140616b730b1d3f96b2c2efcf0ea560de3f2dc21ae950b098f0d1ba2218d`
  and `kaosgdd-ai-governor-discord:rollback-pre-fax-mail-worker` at
  `sha256:6f5ef03f0717b623bf3c0f133a554244535e9b33ebbe4960c0bee560a62590eb`

Production observation is active. One organic new mail or final fax state must
advance the existing checkpoint/action ledger and produce exactly one simple
worker-delivered Pushover record without a Discord archive upload. No synthetic
alert is required.

Risk: medium around one-writer ownership, existing mail/fax checkpoints,
connector availability, and direct fax submissions during reconciliation.

Rollback: stop the worker-owned pollers, restore both owner settings to
`discord`, recreate the retained KaosDiscoord and worker images, and preserve
the same mail, fax, and Pushover state. No HylaFAX, Naver mailbox, Paperless,
database, or archive migration is involved.

Risk: high around worker lifecycles currently started by the H3 Discord bot,
persistent views/state, duplicate notification delivery, and historical
mail/fax/document messages.

Rollback: retain current process commands, bot tokens, channel IDs, state
paths, and disabled channel configuration through each replacement's
observation period.

## Phase 6 — Personal PWA and Stable iOS Interfaces

Status: in progress; read-only supplies pilot exists and stable PWA deep links
are the first implementation slice.

Objective:

- Retain and incrementally evolve the existing personal KaosGDD PWA as the
  primary visual console.
- Provide stable deep links and narrow authenticated APIs for Shortcuts without
  duplicating source-of-truth data.
- Use Scriptable only when a widget or focused interaction is materially better
  than the PWA and Shortcuts. It is not a required application container.
- Replace retiring direct Discord surfaces only after their PWA/Shortcut path
  passes production observation.

PWA surface target:

- Today and daily digest detail
- calendar and tasks
- supplies
- fax send/recent status
- Memos recent/search/create with authoritative upstream links
- Paperless inbox/search/capture status with authoritative upstream links
- system status/settings where the actor is authorized

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
- continue synchronizing native Calendar/Reminders through Radicale for native
  scheduled notifications; their visual UI is optional
- preserve strict hostname, actor, and server-side scope separation between
  personal and Family PWA requests
- keep `/shortcuts/supplies` as a compatibility route during migration

Required deliverables:

- versioned API contract and authentication tests
- committed example Shortcuts instructions
- personal KaosGDD Home Screen installation and stable deep-link instructions
- optional focused Scriptable client only for an identified widget/UI gap
- authoritative Memos and Paperless exact-item link instructions
- iOS Share Sheet capture into Paperless through a scoped endpoint
- on-demand mail/fax/status views or Brain queries for information previously
  shown in direct Discord channels
- no background state database on iOS

Phase 6 slice 1 — stable selected-date PWA link:

- support `#/calendar?date=YYYY-MM-DD` in the existing personal/family portal
- validate real calendar dates before changing presentation state
- do not perform a write, expand scope, or add an authentication bypass
- retain the existing `?weather=YYYY-MM-DD` behavior
- document the route as the first Shortcut-safe PWA entry point

Risk: low. This changes initial calendar presentation only. Invalid dates are
ignored and the existing selected date remains unchanged.

Rollback: remove the `date` deep-link parser and retain `#/calendar`; no API,
database, Radicale object, credential, or deployment state changes.

Phase 6 slice 1 local validation (2026-08-30):

- four focused Node tests cover real/leap dates, invalid normalized dates,
  parameter selection, and missing values
- `node --check` passes for `deep-links.js` and the existing `app.js`
- H3 deploy-helper Bash validation and the live `services-preflight` pass
- CI now runs the PWA checks and uses the canonical
  `integrations/discoord/Dockerfile` path
- the corrected canonical test-image path builds successfully; 250 Governor
  tests (11 PostgreSQL integration tests skipped in the unit image) and 368
  KaosDiscoord tests pass
- no production asset, API, database, Radicale object, credential, or runtime
  process changed

Phase 6 slice 1 production deployment (2026-08-30):

- commit `0d9448a` was pushed to `main` and the clean H4 checkout was
  fast-forwarded to the same commit without restarting Brain
- `family-portal-sync` copied only the committed static source/config set,
  validated nginx, reloaded it, and passed migrated-service preflight
- internal edge requests for both `kaosgdd.net` and `family.kaosgdd.net`
  returned HTTP 200 for the index and `deep-links.js`
- the deployed helper matches the repository source byte-for-byte; the portal
  container is running with zero restarts
- the post-sync service preflight passes and the H4 doctor reports repository,
  Brain, KaosAI, Ollama, Governor, imaging, and system-controller dependencies
  ready
- no Governor, worker, Radicale, mail, fax, Paperless, PACS, or Brain runtime
  was restarted or migrated

Rollback: restore the prior portal static assets from commit `d70dabf`, run
`family-portal-sync`, and retain every backend and source-of-truth service
unchanged.

Phase 6 slice 2 — compact personal main menu:

- replace the growing personal navigation list with one native selector
- expose exactly Agenda, Calendar, Tasks, Memos, Documents, Fax, Mail, Utils,
  and Settings in that order
- keep Family navigation unchanged
- retain the existing route ownership for Calendar/Task editors and Utils
  service detail pages
- expose Fax and Mail as explicit transition notices until their scoped read
  APIs are connected; do not imply that an unavailable writer succeeded
- perform no API call or mutation merely because the selected menu changes

Risk: low. This changes personal navigation and adds two presentation-only
routes. It does not alter an API, credential, data store, notification worker,
or authoritative object.

Rollback: restore the prior direct personal navigation renderer and remove the
Fax/Mail presentation routes. Backends remain unchanged.

Phase 6 slice 2 local validation (2026-08-30):

- four focused navigation tests cover the exact accepted order, uniqueness,
  subroute ownership, safe fallback, and script load order
- the four existing date/deep-link tests continue to pass
- JavaScript syntax, deploy-helper Bash syntax, and `git diff --check` pass
- no production asset or service changed during local validation

Phase 6 slice 2 production deployment (2026-08-30):

- commit `216d1ba` was pushed to `main`
- `family-portal-sync` validated nginx, reloaded the static portal, and passed
  migrated-service preflight
- both `kaosgdd.net` and `family.kaosgdd.net` return HTTP 200 for the portal
  and versioned navigation helper
- deployed HTML, application JavaScript, navigation contract, and CSS match
  repository sources byte-for-byte
- the deployed selector reports the exact accepted nine-item order and retains
  Utils ownership for service subroutes
- portal, Caddy, calendar adapter, Governor API, worker, and KaosDiscoord remain
  healthy/running with zero restarts
- no API, credential, task, event, memo, document, fax, mail, notification, or
  authoritative backend was changed
- follow-up commit `ba15c8e` made the selector itself the visible page title,
  removing the duplicate route heading and visible menu caption; versioned CSS
  was synced byte-for-byte with zero service restarts
- follow-up commit `d7b7c2d` flattened the selector, removed its border and
  native chevron, and uses `•` as the only dropdown indicator
- follow-up commit `a7a8643` also removes every focus/active outline, border,
  shadow, background, and tap highlight from the selector

Rollback: restore the static portal from commit `c9f1bc0` and run
`family-portal-sync`. No data reconciliation is required.

Phase 6 slice 3 — reuse Kaos Memos and add a Kaos Paperless UI:

- run the existing `kaosgdd-memos-web` image as a personal H3 client and point
  only the personal `/memos-app/` route to it
- preserve the separate working Family Memos client and configuration
- replace the obsolete personal temporary-document queue with a read-only
  Paperless recent/search/paging/detail/OCR interface
- expose Paperless through a narrow same-origin `/api/paperless/documents`
  contract on Governor API; do not expose the broad Brain tools token or the
  Paperless API token to the browser
- cryptographically verify the Cloudflare Access assertion and require the
  personal profile before returning document metadata or OCR
- keep Memos and Paperless authoritative and store no duplicate browser-side
  state

Risk: medium. This adds a sensitive read path for document OCR and changes the
personal Memos runtime target. The read API is fail-closed without a valid
Cloudflare assertion, Family is rejected, and no Paperless mutation is in this
slice.

Phase 6 slice 3 validation and deployment (2026-08-31):

- commit `e0a7ac9` was pushed to `main`, fast-forwarded to the clean H4
  checkout, and H4 doctor passed without restarting Brain
- 11 focused portal tests pass, including Paperless normalization and search
  pagination; both JavaScript files pass syntax validation
- six new Paperless API tests, all 15 existing Paperless adapter tests, and all
  six Memos relay tests pass
- the canonical container suite passes 256 Governor tests (11 PostgreSQL tests
  skipped in the unit image) and 368 KaosDiscoord tests
- the personal Memos client is running on H3 with `personal`/Nord configuration;
  local edge requests return its versioned application and configuration
- Governor API is healthy, reads its group-protected Paperless token as the
  non-root service user, and reports 26 live Paperless documents
- unauthenticated Paperless requests return HTTP 401 at Governor and through
  the same-origin edge; they do not fall through to the SPA
- the portal serves versioned `documents.js`, application JavaScript, and CSS;
  nginx configuration and migrated-service preflight pass
- an nginx bind-mount inode issue found during deployment was corrected by
  recreating the stateless portal whenever its tracked nginx configuration is
  synchronized

Production observation remains open for a normal authenticated personal Memos
session and Paperless browse/search/detail/link flow. Paperless upload, metadata
mutation, and AI proposal/confirmation UI are follow-up slices.

Rollback: restore `kaosgdd-ai-governor-api:rollback-pre-paperless-20260831`,
restore the prior portal assets/config, and remove the personal Memos client
route. No Memos or Paperless data reconciliation is required.

Phase 6 slice 4 — Archive Terminal for Documents and Fax:

- introduce one scoped personal `Archive Terminal` presentation pattern for
  BBS-style document boards
- restyle the existing read-only Paperless browser using that terminal pattern
  while preserving the same `/api/paperless/documents` API, search, pagination,
  detail, OCR, and source-link behavior
- expose a new read-only same-origin `/api/fax/items` browser backed by the
  existing KaosGovernor HylaFAX archive state
- expose retained incoming fax PDFs through
  `/api/fax/items/{fax_id}/document` only after the same personal Cloudflare
  Access verification used by Paperless
- mount Fax state read-only into the Governor API container and proxy only
  `/api/fax/` through the personal portal
- keep Fax send, retry, delete, Paperless upload, and metadata mutation out of
  this slice

Risk: medium. This adds a sensitive read path for retained incoming fax PDFs
and changes the Documents presentation. The API is GET-only, personal-only,
strictly validates IDs and modes, and does not take a HylaFAX write lock.

Required validation:

- focused portal normalization/navigation tests
- JavaScript syntax checks for portal scripts
- focused Fax API and Fax service tests in the Governor test image
- live H3 smoke against the read-only fax archive mount
- nginx and Compose validation
- unauthenticated Governor and edge requests must fail closed
- authenticated personal observation for Documents and Fax after deployment

Rollback: restore the previous static portal assets, remove the `/api/fax/`
nginx proxy, and roll Governor API back to the retained pre-Fax image. Fax,
Paperless, Memos, Radicale, mail, and notification data need no reconciliation.

Phase 6 slice 4 validation and deployment (2026-08-31):

- commit `bfbd709` was pushed to `main`, deployed on H3, and H4 was
  fast-forwarded to the same commit with Brain doctor passing
- 15 focused portal tests pass; `app.js`, `documents.js`, and `fax.js` pass
  JavaScript syntax validation
- the canonical test image passes 265 Governor tests with 11 PostgreSQL-gated
  tests skipped and 368 KaosDiscoord tests
- services and family-transition preflights pass; `git diff --check` passes
- Governor API was rebuilt/recreated only for the family-transition API role;
  KaosDiscoord and the worker stayed on their existing healthy containers
- the prior API image is retained as
  `kaosgdd-ai-governor-api:rollback-pre-archive-terminal-20260831`
- the live read-only Fax archive reports 7 records: 3 received, 3 sent, and 1
  failed; all 3 received rows expose retained PDFs and outgoing rows do not
- a retained incoming PDF was read from the API container with `%PDF-` content
  and a 29,737-byte payload
- the portal serves versioned `styles.css?v=232`, `fax.js?v=1`, and
  `app.js?v=222`, and deployed static files match Git byte-for-byte
- unauthenticated Fax requests return HTTP 401 both directly at Governor API
  and through the same-origin portal route

Authenticated user observation remains open for Documents search/detail/OCR,
Fax board mode switching, Fax detail, and retained PDF open behavior.

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

## Phase 8 — Governed Brain System Operations

Status: planned. The current Brain Guard continues to reject system, shell,
Docker, database, and restart intents.

Objective:

- Make `#brain` and future Ask Kaos clients a conversational system-operations
  console without giving the model privileged host access.

Planned implementation:

1. Move read-only system inventory and health aggregation out of KaosDiscoord
   and behind Governor-owned APIs.
2. Add read-only `system.status` to Brain Guard and the personal admin PWA.
3. Define versioned runbook contracts and dry-run-only restricted host
   executors.
4. Add one allowlisted non-critical restart with exact confirmation, audit,
   verification, and a deterministic non-AI caller.
5. Add pinned Kaos application deployment/rollback only after backup and
   recovery tests pass.
6. Keep PACS/database/OS upgrades in a separately hardened maintenance track.

Security and rollback requirements are defined in [Brain as Kaos Gateway and
System Operator](../architecture/brain-system-operations.md). No phase may
replace the deny-by-default Guard with arbitrary commands, SSH, sudo, Docker
socket access, or model-visible secrets.

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
| 2026-08-30 | 3 | Routed direct Discord Memos mutations through the shared Governor lifecycle | Commit `7c9f577`; 24 focused Memos + 231 Governor + 11 isolated PostgreSQL + 355 Discord + 321 Brain tests passed; authoritative result prevents a post-write read failure; retries do not repeat writes | None; locally validated and awaiting controlled H3 deployment |
| 2026-08-30 | 3 | Promoted direct Discord Memos governed execution to H3 | Installed runtime confirms governed create/edit/delete and shared durable objects; container healthy with zero restarts; 5 completed operations retained with 0 payloads; H4 doctor healthy and checkout synced | Slice 2 production observation started; rollback image `kaosgdd-ai-governor-discord:rollback-1e6a3aa` retained |
| 2026-08-30 | Decision | Narrowed Discord's target role to the single H4 `#brain` topic | Added the accepted brain-only architecture decision, replacement matrix, worker-detachment requirement, channel history gates, and revised Phases 5-6 | No channel disabled; direct surfaces remain compatibility paths until replacements are observed |
| 2026-08-30 | 5 | Completed the local Governor-side KaosDiscoord package extraction | Canonical package/executable plus thin legacy shims; dependency boundary enforced; 231 Governor + 358 KaosDiscoord + 321 Brain tests; H3 preflight and Compose render passed | None; deployment pending, current service/image/container identity retained |
| 2026-08-30 | 5 | Promoted the KaosDiscoord package boundary to H3 | Commit `20732fa`; canonical runtime entry point and package installed; legacy imports resolve to canonical classes; container healthy/ready with zero restarts; ledger retained 5 completed operations and 0 payloads; H4 synced and doctor healthy | Compatibility observation started; rollback image `kaosgdd-ai-governor-discord:rollback-pre-kaosdiscoord` retained |
| 2026-08-30 | 5 | Implemented the independent Pushover delivery worker | Lifecycle inventory plus dedicated image/entry point, queue-only producer mode, cross-process state lock, worker heartbeat, and guarded Compose ownership; 237 Governor + 359 KaosDiscoord + 321 Brain tests passed | None; locally validated, production cutover pending |
| 2026-08-30 | 5 | Promoted independent Pushover delivery to H3 | Commit `356e1b4`; sequenced one-writer cutover; worker and KaosDiscoord healthy with zero restarts; queue state preserved at 0 pending/7 delivered; ledger retained 5 completed/0 payloads; H4 synced and healthy | Production observation started; rollback image `kaosgdd-ai-governor-discord:rollback-pre-pushover-worker` retained |
| 2026-08-30 | 5 | Completed independent Pushover delivery production observation | An organic one-page incoming fax was archived on H3; KaosDiscoord queued one keyed `Fax received.` record and `kaos-governor-worker` delivered it one second later; outbox moved from 7 to 8 delivered with 0 pending; both containers remained healthy with zero restarts | Slice 2 complete; rollback image remains retained while the next worker lifecycle is selected |
| 2026-08-30 | 5 | Implemented worker-owned daily-digest scheduling and per-alert Pushover priority | Worker owns due/build/enqueue and persists a locked Discord publication; KaosDiscoord is transport-only for the transitional controls; routine alerts are priority 0 and actionable failures priority 1; 240 Governor + 361 KaosDiscoord tests passed; H3 preflight passed | Locally validated; controlled H3 cutover and next organic 07:00 observation pending |
| 2026-08-30 | 5 | Promoted worker-owned daily-digest scheduling and per-alert priority to H3 | Commit `58e5237`; owner switched after preserving today's sent-date; no duplicate digest/alert; worker and KaosDiscoord healthy with zero restarts; outbox 0 pending/8 delivered; H4 doctor passes | Production observation started; retained rollback images cover both processes; next organic 07:00 is the gate |
| 2026-08-30 | 5 | Implemented worker-owned Naver mail and fax polling | Neutral lifecycle workers retain IMAP/fax sources, queue only minimal final alerts, persist cross-process status, lock shared fax state, and leave only source-message deletion in KaosDiscoord; 250 Governor + 368 KaosDiscoord + 321 Brain tests passed; runtime/preflight checks pass | Locally validated; production remains Discord-owned pending the guarded cutover |
| 2026-08-30 | 5 | Promoted worker-owned Naver mail and fax polling to H3 | Commit `3d98e40`; mail/fax checkpoints and Pushover state preserved; both worker-owned timestamps advanced; Brain list routes returned HTTP 200; both containers and H4 dependencies are healthy | Production observation started; no duplicate alert or Discord archive upload; both prior images and three state snapshots retained |
| 2026-08-30 | 6 | Recorded deferred Shortcut deep-link support for opening a selected Memos item | Existing Memos route and ID mapping verified as `/m/{memo-id}`; iOS external-link/PWA limitation documented | None; planning only |
| 2026-08-30 | Decision | Retained the personal KaosGDD PWA as the primary visual console with Shortcuts as the iOS integration layer | Architecture, authority, personal/family scope, native CalDAV relationship, Scriptable optionality, and incremental delivery recorded | Supersedes the earlier no-personal-PWA assumption; no production route changed |
| 2026-08-30 | Decision | Defined Brain's future as both a KaosGDD language gateway and a governed system-operations console | Typed operation, host-executor, confirmation, upgrade, PACS-isolation, and availability boundaries recorded | Current system/restart Guard rejection remains active; no privileged capability added |
| 2026-08-30 | 6 | Implemented and locally validated the first personal-PWA/Shortcut deep link | Four focused tests, both portal syntax checks, deploy-helper Bash validation, `git diff --check`, H3 `services-preflight`, 250 Governor tests, and 368 KaosDiscoord tests passed; CI covers the route helper | `#/calendar?date=YYYY-MM-DD` is ready for controlled sync; no backend or production change |
| 2026-08-30 | 6 | Promoted the selected-date PWA/Shortcut deep link | Commit `0d9448a`; nginx validation/reload and service preflight passed; both personal and Family host profiles returned HTTP 200 and served a byte-matching helper; portal zero restarts; H4 synced and doctor healthy | Slice 1 deployed; rollback is the prior static source at `d70dabf`; no backend/runtime restart or data migration |
| 2026-08-30 | Decision | Reconciled the host migration plan, production plan, and repository overview with the retained personal-PWA decision | Cross-document search removed the stale no-personal-portal and native-UI-primary assumptions | Documentation only; deployed services and data unchanged |
| 2026-08-30 | 6 | Implemented and locally validated the compact personal main-menu selector | Exact nine-item order, subroute ownership, fallback, and asset load order covered by focused tests; existing deep-link tests and syntax checks pass | Awaiting controlled static-portal promotion; Family navigation and all backends unchanged |
| 2026-08-30 | 6 | Promoted the compact personal main-menu selector | Commit `216d1ba`; both host profiles serve byte-matching versioned assets; exact menu order verified; migrated-service preflight passed; related containers retained zero restarts | Slice 2 deployed; rollback is static commit `c9f1bc0`; no backend or data change |
| 2026-08-30 | 6 | Made the personal selector the sole visible page title | Commit `ba15c8e`; duplicate route heading and visible menu caption removed; deployed HTML/CSS match Git; portal and Governor workers retained zero restarts | Presentation-only follow-up; backend and Family behavior unchanged |
| 2026-08-30 | 6 | Flattened the personal title selector | Commit `d7b7c2d`; transparent borderless selector with `•` indicator; versioned CSS matches production; portal retained zero restarts | Presentation-only follow-up; no backend or data change |
| 2026-08-30 | 6 | Kept the selector borderless while focused or active | Commit `a7a8643`; focus/active outline, shadow, background, border, and tap highlight removed; versioned CSS matches production | Presentation-only follow-up; no backend or data change |
| 2026-08-31 | 5 | Completed worker-owned daily-digest production observation | Organic `Good Morning.` scheduled at 07:00:12 KST and delivered by Pushover at 07:00:13 KST; outbox reached 9 delivered/0 pending; no errors; user confirmed receipt; worker and KaosDiscoord healthy with zero restarts | Slice 3 complete; no synthetic notification needed |
| 2026-08-31 | 6 | Restored the existing personal Kaos Memos client and deployed the KaosGDD Paperless browser | Commit `e0a7ac9`; 11 portal tests; 6 new API + 15 adapter + 6 relay tests; canonical 256 Governor/368 KaosDiscoord suite; H4 synced/healthy; Memos personal config served locally; Paperless reports 26 documents; unauthenticated edge/API reads fail HTTP 401 | Read-only Paperless and personal Memos UI deployed; authenticated user observation open; rollback API image retained |
| 2026-08-31 | 6 | Rebalanced the personal compact header with the flat page selector on the left, a matching-size `KaosGDD` wordmark on the right, and both vertically centered in the same 44 px row | Versioned stylesheet `v231`; 11 focused portal tests passed; deployed assets and H4 sync are verified during promotion | Presentation-only follow-up; Family header, routes, APIs, data, and Brain runtime remain unchanged |
| 2026-08-31 | 6 | Implemented and locally validated the first Archive Terminal slice for Documents and Fax | Read-only personal Fax API and PDF route, scoped BBS-style Documents/Fax UI, versioned `fax.js`, source preflight guard, 15 portal tests, syntax checks, `git diff --check`, services/family preflight, and canonical 265 Governor + 368 KaosDiscoord image tests pass | Local validation complete; H3 promotion and authenticated user observation pending |
| 2026-08-31 | 6 | Promoted Archive Terminal Documents/Fax to H3 and synced H4 | Commit `bfbd709`; API image rebuilt with rollback tag retained; portal assets match Git; live Fax archive reports 7 records and 3 retained PDFs; unauthenticated API/portal requests fail HTTP 401; H4 doctor passes at the same commit | Authenticated user observation open; no Fax, Paperless, Memos, Radicale, mail, notification, Discord, or worker mutation occurred |
| 2026-08-31 | 6 | Simplified the personal selector and Archive Terminal action labels | Removed the top selector `•` indicator and bracketed Archive Terminal button text; versioned `styles.css?v=233` and `app.js?v=223`; 15 portal tests, JavaScript syntax checks, and `git diff --check` pass | Presentation-only follow-up; static portal promotion pending |
| 2026-08-31 | 6 | Corrected the Tasks Add button height | Forced the Add control to the same 44 px block size as the task filters and versioned `styles.css?v=234`; 15 portal tests, JavaScript syntax check, and `git diff --check` pass | Presentation-only follow-up; static portal promotion pending |
| 2026-08-31 | 6 | Corrected the Tasks Add button row placement | Added a filter-row spacer slot so Add occupies only the select row; versioned `styles.css?v=235` and `app.js?v=224`; 15 portal tests, JavaScript syntax check, and `git diff --check` pass | Presentation-only follow-up; static portal promotion pending |
| 2026-08-31 | 6 | Extended the Archive Terminal visual language across the personal PWA | Personal profile now uses Sarasa Gothic Mono by default and ignores prior non-mono font preferences; common personal panels, controls, rows, and calendar surfaces use darker Nord variables and rectangular corners; versioned `styles.css?v=236` and `app.js?v=225` | Presentation-only follow-up; Family styling unchanged; static portal promotion pending |
| 2026-08-31 | 6 | Changed Rouny timetable blocks to vertical emoji/title layout | Rouny class blocks now render emoji above the class title so titles can use the full block width; mobile and print overrides follow the same layout; versioned `styles.css?v=237`; 15 portal tests, JavaScript syntax check, and `git diff --check` pass | Presentation-only follow-up; static portal promotion pending |
| 2026-08-31 | 6 | Matched iOS bottom safe-area color to personal content | Personal body and view now use the same dark content background and view padding includes `safe-area-inset-bottom`; versioned `styles.css?v=238`; 15 portal tests, JavaScript syntax check, and `git diff --check` pass | Presentation-only follow-up; static portal promotion pending |
| 2026-08-31 | 6 | Reordered the personal header to brand then menu | Mobile personal header now renders `KaosGDD` on the left and the selected-page dropdown on the right; versioned `styles.css?v=239`; 15 portal tests, JavaScript syntax check, and `git diff --check` pass | Presentation-only follow-up; static portal promotion pending |
| 2026-08-31 | 6 | Added faint host label above the personal dropdown | The right-side menu now includes a faint `kaosgdd.net` label above the selected page while keeping the dropdown functional; versioned `styles.css?v=240` and `app.js?v=226`; 15 portal tests, JavaScript syntax check, and `git diff --check` pass | Presentation-only follow-up; static portal promotion pending |
| 2026-08-31 | 6 | Removed personal pill chrome from owner/automation/all-day labels | Personal `calendarPill` and `timelineAllDayPill` labels keep their semantic text colors but no longer render borders, backgrounds, rounded boxes, or padding; versioned `styles.css?v=241` | Presentation-only follow-up; static portal promotion pending |
| 2026-08-31 | 6 | Aligned the personal host label with the header row | `kaosgdd.net` now sits on the same baseline as the selected menu text, uses matching header size, and remains faint/right-aligned; versioned `styles.css?v=242` | Presentation-only follow-up; static portal promotion pending |
| 2026-08-31 | 6 | Corrected personal header row placement | Forced the selected menu and `kaosgdd.net` host label onto the same CSS grid row after mobile Safari rendered them on separate rows; versioned `styles.css?v=243` | Presentation-only follow-up; static portal promotion pending |
| 2026-08-31 | 6 | Made the personal host label fainter | Reduced the `kaosgdd.net` header label opacity while keeping its row placement and size unchanged; versioned `styles.css?v=244` | Presentation-only follow-up; static portal promotion pending |
| 2026-08-31 | 6 | Restored vertical centering for text-only personal labels | Text-only owner/automation/all-day labels now keep inline-flex centering and agenda rows center their time/title columns; versioned `styles.css?v=245` | Presentation-only follow-up; static portal promotion pending |
| 2026-08-31 | 6 | Converted the faint personal host label into a URL link | The faint header label now displays `kaosgsd.net` and links to `https://kaosgsd.net`; versioned `styles.css?v=246` and `app.js?v=227`; navigation contract expectation updated | Presentation-only follow-up; static portal promotion pending |
| 2026-08-31 | 6 | Reverted the personal host text to a very faint static label | Removed the external link behavior and rendered `kaosgsd.net` as a non-clickable label at lower opacity; versioned `styles.css?v=247` and `app.js?v=228` | Presentation-only follow-up; static portal promotion pending |
| 2026-08-31 | 6 | Matched the Tasks Add button height to the dropdown controls | Removed the fake label spacer above the Add button so it renders as only the 44 px control row; versioned `app.js?v=229` | Presentation-only follow-up; static portal promotion pending |
| 2026-08-31 | 6 | Removed redundant Documents and Fax archive mastheads | Dropped the in-content `DOCUMENT ARCHIVE` and `FAX BOARD` masthead blocks so the top page selector remains the only page title; versioned `app.js?v=230` | Presentation-only follow-up; static portal promotion pending |
| 2026-08-31 | 6 | Removed visible filename fallbacks from Documents | Document rows and details now show title/correspondent only, falling back to `Document #id` and `UNKNOWN` instead of filenames; versioned `documents.js?v=2` and `app.js?v=231` | Presentation-only follow-up; static portal promotion pending |
| 2026-08-31 | 6 | Corrected the personal host label text | The faint non-clickable header label now reads exactly `https://kaosgdd.net`; versioned `app.js?v=232` | Presentation-only follow-up; static portal promotion pending |
| 2026-08-31 | 6 | Corrected the personal owner display label | Portal-owned UI now displays the personal collection label as `GDDZiN` instead of `GDD_ZiN`; versioned `app.js?v=233` | Presentation-only follow-up; static portal promotion pending |
| 2026-08-31 | 6 | Moved Fax refresh into the mode row | Fax archive refresh now renders as a compact `↻` button on the same line as the board filters; versioned `styles.css?v=248` and `app.js?v=234` | Presentation-only follow-up; static portal promotion pending |
| 2026-08-31 | 6 | Stacked caregiver month-cell duration text | Family `돌봄` monthly grid cells now render mixed durations as `3시간` then `30분` on separate lines while totals/daily rows stay one-line; versioned `styles.css?v=249` and `app.js?v=235` | Presentation-only follow-up; static portal promotion pending |
| 2026-08-31 | 6 | Added caregiver monthly summary copying | Family `돌봄` monthly details now include a `복사` action that copies a sendable plain-text month/payment/daily summary for the caregiver; versioned `styles.css?v=250` and `app.js?v=236` | Presentation-only follow-up; static portal promotion pending |
| 2026-08-31 | 6 | Changed caregiver sharing to an image preview | The Family `돌봄` `복사` action now opens a rendered monthly calendar/payment image preview with save and text-copy actions; versioned `styles.css?v=251` and `app.js?v=237` | Presentation-only follow-up; static portal promotion pending |
| 2026-09-01 | 6 | Restored Supplies as a first-class personal menu item | Personal dropdown now includes `Supplies` after `Tasks`, and `#/supplies` selects the Supplies menu instead of aliasing to Utils; versioned `navigation.js?v=2` and `app.js?v=238` | Presentation-only follow-up; static portal promotion pending |
| 2026-09-01 | 6 | Kept only Memos tags rounded in the embedded web client | Commit `64aa5d0`; added tracked `kaosgdd-memos-web:0.1.6-rectangular-controls` image layer; portal checks pass; Caddy serves the appended override and both Memos web containers run the new image | H3 promoted; H4 synced and KaosBrain doctor passes |
| 2026-09-01 | 6 | Normalized personal Tasks and Memos action button heights | Commit `5dd54ad`; Tasks Add no longer stretches to the label row; embedded Memos search and `+` controls share a compact 44 px height while tag chips stay rounded; versioned `styles.css?v=252`; 15 portal tests pass and served files are byte-synced | H3 promoted; H4 synced and KaosBrain doctor passes |
| 2026-09-01 | 6 | Forced Tasks Add button to the dropdown control height | Commit `4b1fb98`; added a late personal-profile override that caps the Tasks Add slot and button at 44 px with high specificity; versioned `styles.css?v=253`; served CSS and byte sync verified | H3 promoted; H4 synced and KaosBrain doctor passes |
| 2026-09-01 | 6 | Aligned Tasks Add button to the dropdown row | Commit `5df6bd9`; replaced the over-capped Add container with a hidden label spacer plus fixed 44 px button row so mobile Safari aligns Add with the select controls; versioned `styles.css?v=254`; served CSS and byte sync verified | H3 promoted; H4 synced and KaosBrain doctor passes |
| 2026-09-01 | 6 | Moved Tasks Add into the collection selector row | Commit `5d9d5c6`; Tasks now renders `All / Family / GDDZiN / Add`, with Add as a highlighted rectangular collection-row action; the lower filter row is only Tasks and Order; versioned `styles.css?v=255` and `app.js?v=239`; served assets and byte sync verified | H3 promoted; H4 synced and KaosBrain doctor passes |
| 2026-09-01 | 6 | Matched Documents top controls to the Memos layout | Commit `d72a0d0`; Documents search now uses a wide rectangular search box with a compact highlighted `↻` refresh action on the right; search submits with Return and clear is inline; versioned `styles.css?v=256` and `app.js?v=240`; served assets and byte sync verified | H3 promoted; H4 synced and KaosBrain doctor passes |
| 2026-09-01 | 6 | Reduced PWA bottom safe-area reserve | Commit `84d4bd6`; Main PWA pages now use a minimal `max(8px, safe-area-inset-bottom)` bottom reserve instead of 40 px; embedded Memos image override uses the same minimal bottom reserve; versioned `styles.css?v=257` and `kaosgdd-memos-web:0.1.7-minimal-safe-area`; served CSS and container image verified | H3 promoted; H4 synced and KaosBrain doctor passes |
| 2026-09-01 | 6 | Simplified archive rows to number, date, and one-line title | Commit `dafdbe6`; Documents and Fax archive boards now omit list-row correspondent/status fields and render title as one-line ellipsis; detail panels retain metadata; versioned `styles.css?v=258` and `app.js?v=241`; served assets and byte sync verified | H3 promoted; H4 synced and KaosBrain doctor passes |
| 2026-09-01 | 6 | Removed redundant Supplies content header | Commit `40b8181`; Full Supplies page no longer renders the in-panel `Supplies / Buy list / Utils` header; the top PWA title remains the only page header; versioned `app.js?v=242`; served JS and byte sync verified | H3 promoted; H4 synced and KaosBrain doctor passes |
| 2026-09-01 | 6 | Added global top-right quick add action | Commit `5c2a153`; replaced the decorative main header host label with a page-aware `+`; tap opens the current page add action where wired, long-press opens Task/Event/Supply/Memo/Document/Fax/Mail selector, and dummy actions alert for unwired flows; removed duplicated main content Add buttons for Tasks, Calendar, full Supplies, and embedded Memos; versioned `styles.css?v=259`, `app.js?v=243`, and `kaosgdd-memos-web:0.1.8-top-add-shell`; served assets, byte sync, and Memos image verified | H3 promoted; H4 synced and KaosBrain doctor passes |
| 2026-09-01 | 6 | Made the shell quick-add button circular | Commit `1c25852`; top-right `+` is now the only rounded control exception in the main shell while the rest of the PWA controls stay rectangular; versioned `styles.css?v=260`; served CSS and byte sync verified | H3 promoted; H4 synced and KaosBrain doctor passes |
| 2026-09-01 | 6 | Standardized main PWA pages against the Agenda baseline | Commit `4bd3401`; added a main-profile CSS baseline for shared panel rhythm, spacing, rectangular controls, panel/header sizing, archive shell alignment, and Memos containment while preserving the circular shell `+` and rounded tag exceptions; versioned `styles.css?v=261`; served CSS and byte sync verified | H3 promoted; H4 synced and KaosBrain doctor passes |
| 2026-09-01 | 6 | Added native one-box memo composer | Commit `5b73eb1`; added `/add-memo` as a Memos-owned main route; top-right `+` on Memos now opens a native one-textarea composer that posts private memo content through the existing Governor Memos relay and returns to the embedded Memos list; versioned `translations.js?v=171`, `navigation.js?v=3`, `styles.css?v=262`, and `app.js?v=244`; served assets, byte sync, Caddy relay boundary, and 17 frontend tests verified | H3 promoted; H4 synced and KaosBrain doctor passes |
| 2026-09-01 | 6 | Added Documents Archive/Inbox mode tabs | Documents now has a Tasks-like two-mode selector: Archive preserves the existing Paperless search/list/detail board, while Inbox is a prepared intake board placeholder for the upcoming upload/OCR/manual-review workflow; versioned `styles.css?v=263` and `app.js?v=245`; JavaScript syntax check, 17 frontend tests, `git diff --check`, nginx validation, and served-file byte sync pass | H3 static portal promoted; no backend, Paperless, OCR, or data mutation occurred |
| 2026-09-01 | 6 | Normalized main-profile active tab highlights | Main PWA tab-like controls now share the Tasks active state: Radicale collection tabs, segmented tabs, embedded switchers, Documents Archive/Inbox, and Fax mode buttons use the same pink/purple rectangular highlight; versioned `styles.css?v=264`; JavaScript syntax check, 17 frontend tests, `git diff --check`, nginx validation, and served-file byte sync pass | H3 static portal promoted; no backend or data mutation occurred |
| 2026-09-01 | 6 | Reworked embedded Memos layout to match the PWA card model | Memos wrapper no longer renders as one large card; search and tags sit on the page surface, while each memo record gets its own full rectangular card border; versioned `styles.css?v=265` and `kaosgdd-memos-web:0.1.9-card-feed`; JavaScript syntax check, 17 frontend tests, `git diff --check`, local image build, nginx validation, served-file byte sync, and live container image checks pass | H3 static portal and both Memos web containers promoted; backend services and data unchanged |
| 2026-09-01 | 6 | Matched embedded Memos dark background to the main PWA | The personal embedded Memos Nord theme now uses the portal's main dark `--bg`, `--panel`, `--surface`, and line colors so iframe edges no longer show a different dark strip; versioned `kaosgdd-memos-web:0.1.10-background-match`; 17 frontend tests, `git diff --check`, local image build, live container image checks, and live CSS override checks pass | H3 Memos web containers promoted; backend services and data unchanged |
| 2026-09-01 | 6 | Replaced personal Memos iframe with a native archive board | Personal Memos now renders through the main PWA using the shared Archive Terminal UI, reads list/search data from the existing Governor Memos relay, shows memo rows as number/date/title only, and keeps memo details local to the loaded list response without widening backend relay permissions; versioned `styles.css?v=266` and `app.js?v=246`; JavaScript syntax check, 18 frontend tests, and `git diff --check` pass | Local validation complete; static portal promotion pending |

## How to Update This Tracker

For every implementation turn:

1. Mark the phase **In progress** before broad code changes.
2. Record the exact scope and any changed assumptions.
3. Update the affected-files, risk, tests, and rollback sections.
4. Record test counts and production impact in the progress log.
5. Distinguish local validation, commit, deployment, and observation; do not
   call a phase complete merely because code exists.
6. Never mark a production gate complete without direct evidence.
