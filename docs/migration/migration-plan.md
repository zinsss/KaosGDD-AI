# Migration Plan

This document tracks the host and stateful-service migration. The active
application-boundary work has a separate canonical
[Brain / Governor / Discoord / iOS implementation tracker](brain-governor-discoord-ios-plan.md).
The two plans use independent phase numbers; always name the plan as well as
the phase when recording progress.

## Implementation status on 2026-08-28

This remains the rollback-aware migration contract, but several phases are now
implemented in production:

- H3 networking, Governor, PostgreSQL, Radicale, Memos, family services, and
  the service edge are active.
- H4 KaosBrain is active with narrow Governor tools and guarded KaosAI/OpenClaw
  chat.
- Discord direct operational surfaces are active during transition, but the
  accepted target retains only the H4 `#brain` topic. Native iOS apps, scoped
  mobile clients, service PWAs, and Pushover replace the other channels under
  the [brain-only decision](../architecture/discord-brain-only.md).
- Naver mail, Memos, Paperless inbox/search, calendar, task confirmations,
  system status, and imaging second-look are active Governor workflows.
- Fax uses the authenticated Office Fax Connector plus the repository-owned
  Office Fax Bridge; HylaFAX and the modem remain at the office.
- KaosFaxMail was never adopted as the production mailbox path and is archived.

Remaining work is verification and cleanup: finish observation gates, verify a
live inbound and outbound fax, retire proven-unused legacy workers, complete
family AI scope, and test backup restoration. Phase descriptions below retain
their original sequencing because they remain useful for rollback and rebuilds.

## Objectives

- Build the H4 Brain and H3+ backend beside production.
- Keep PACS, DICOM, Paperless, RustDesk, and HylaFAX stable at the office.
- Move deterministic orchestration before enabling AI writes.
- Preserve all Radicale and Memos data.
- Retire KaosTelegram instead of migrating it to the H3 backend.
- Keep rollback possible at every cutover.

## Migration Strategies

### Strategy A: Side-by-Side Domain Migration (Recommended)

Build Governor beside the existing Brain. Move one domain at a time using shadow reads, contract tests, and explicit write cutovers.

Advantages:

- smallest blast radius
- easiest data comparison
- independent rollback per domain
- existing production workflows remain available

Disadvantage:

- temporary duplicate adapters and more transition configuration

### Strategy B: Infrastructure-First Migration

Move Radicale, Memos, and web edge to the H3+ backend before refactoring Brain into Governor.

Advantages:

- validates hardware and networking early
- separates office services sooner

Disadvantages:

- moves infrastructure and application behavior at the same time
- combines infrastructure movement with application behavior changes
- gives weaker behavioral isolation

Use Strategy B only for stateless web-edge preparation. Stateful services should still follow the guarded procedure below.

### Strategy C: Big-Bang Replacement

Not approved. It combines host moves, data moves, channel replacement, API replacement, and AI enablement without useful rollback boundaries.

## Phased Plan

### Phase 0: Freeze the Contract Surface

- Inventory current Brain APIs, database tables, background jobs, and credentials.
- Record current service versions and image digests.
- Create representative fixtures for calendar, tasks, mail, fax, Memos, and Paperless.
- Define actor scopes: personal, family, clinic, system.
- Define operation, confirmation, audit, job, and notification schemas.
- Make no production routing changes.

Exit criteria:

- every current Brain capability is assigned to retain, convert, or retire
- initial REST/MCP schemas are reviewable
- current backups can be restored in a test location

### Phase 1: Prepare H3+ and H4 Networking

- Install the H3+ and H4 operating systems on NVMe.
- Set fixed internal names and Tailscale identities.
- Configure time synchronization, SMART monitoring, log limits, and host backups.
- Create empty Compose projects with health checks only when implementation starts.

No production service moves in this phase.

### Phase 2: Governor Foundation on H3+

- Implement Governor API, PostgreSQL migrations, audit, idempotency, operation status, and confirmation tokens.
- Run only read tools against production adapters initially.
- Add shadow comparison tests against the current Brain.
- Do not expose Governor publicly.

Rollback: stop Governor on H3+. Existing Brain remains authoritative.

### Phase 3: Migrate Governor Domains

Suggested sequence:

1. KaosMemos read/search, then create/update.
2. KaosCalendar read/search, then event/task writes.
3. KaosScheduler and recurring/generated calendar jobs.
4. KaosMail polling and Discord presentation.
5. KaosInbox and Paperless import.
6. KaosFax records and the office Fax Connector.
7. KaosNotifications and Web Push.

For each domain:

- port existing deterministic tests first
- run shadow reads and compare normalized results
- test idempotent writes against non-production collections/accounts
- cut over one writer
- observe and reconcile
- disable, but do not delete, the old writer

### Phase 4: Radicale and Memos to H3+

Current production locations at planning time:

- Radicale data: `/srv/kaos/data/radicale`
- Radicale config/users: `/srv/kaos/config/radicale`
- Memos data: `/srv/kaos/data/memos`

Procedure:

1. Pin the exact source versions and image digests.
2. Prepare destination NVMe/SATA storage and permissions.
3. Take a verified backup and initial online copy.
4. Stop all Radicale/Memos writers, including Brain/Governor adapters and custom frontends.
5. Stop Radicale and Memos.
6. Perform a final archive-preserving `rsync` with numeric ownership.
7. Compare file inventory and cryptographic checksums.
8. Start the same application versions on H3+.
9. Test every user, collection, event, task, journal, memo, tag, resource, create, and edit path.
10. Switch one route at a time.
11. Keep original containers stopped and original data untouched through the observation period.

Memos SQLite WAL files require a clean stop before the final copy. Radicale configuration must move with collection data so users and rights are preserved.

Rollback:

- stop H3+ destination services
- restore original routing
- restart original services against untouched original data
- reconcile only writes accepted after cutover, if any

### Phase 5: Web Edge to H3+

- Deploy Family KaosGDD as the supported custom web application.
- Do not deploy the main KaosGDD UI. Retain its repository as reference only.
  The old `kaosgdd-portal` personal/main route is deprecated; keep only the
  family portal surface needed for `family.kaosgdd.net`.
- Keep ready-made backend services under their native operational names. They
  remain part of the KaosGDD project deployment, but do not rename Radicale,
  Memos, Vaultwarden, SFTPGo, Caddy, or cloudflared into `kaosgdd-*` services.
- Deploy Caddy and one cloudflared connector.
- Route to Family KaosGDD and service-native web applications through private
  addresses.
- Move hostnames one at a time.
- Keep native CalDAV requirements separate from interactive Cloudflare Access policy.

Rollback: restore the individual Caddy/tunnel route to the office host.

### Phase 6: Family AI on H4

- Start with a separately scoped family session and one concurrent request.
- Add family-only Governor tools.
- Embed chat in Family KaosGDD.
- Add SSE response streaming, durable family chat messages, and Web Push.
- Test Korean date/time and Rouny commands against a fixed evaluation set.
- Keep all calendar/task writes confirmed until measured reliability is acceptable.

Failure must affect only AI chat, not Family KaosGDD or native services.

### Phase 7: KaosBrain on H4

- Deploy KaosBrain, the local model, and optional KaosAI/OpenClaw planner
  runtime.
- Use a new Discord bot during migration.
- Give KaosBrain only narrow KaosGovernor tool API access.
- Deny shell, SSH, Docker, database, filesystem, and elevated tools to both
  KaosBrain and KaosAI/OpenClaw.
- Start with Memos read/search, then use the same domain order as Governor.
- Benchmark 7-9B and 14B candidates using real Korean Kaos commands.

### Phase 8: Retire KaosTelegram

- Create minimal private Discord channels: `#kaos`, `#inbox`, and `#system`.
- Verify document, mail, fax, confirmation, and cleanup interactions in
  Discord or Governor-owned deterministic services where retained.
- Do not migrate KaosTelegram containers, tokens, bot state, or presentation
  code to the H3 backend.
- Stop KaosTelegram once the retained workflows have a verified Discord,
  Governor, native-app, or manual replacement.
- Archive its Compose/config/state for rollback reference only; do not restart
  it automatically during rollback without an explicit decision.

### Phase 8.1: Personal UI simplification

- Verify personal events in iOS Calendar.
- Verify personal and family tasks plus the supplies list in iOS Reminders.
- Verify Discord covers personal Memos, document, mail, fax, rule, and
  orchestration workflows.
- Use upstream service web UIs only when direct backend access is useful.
- Confirm the main KaosGDD web UI is not part of the target deployment. Start a
  future personal UI only if this parity check exposes a concrete unmet need.
- Family KaosGDD is explicitly retained.

### Phase 9: Reduce the Office H3+

Target services that remain:

- KaosPACS and KaosPACS-AIO
- Paperless
- Stirling-PDF
- RustDesk
- HylaFAX and local Fax Connector
- Tailscale
- internal reverse proxy only if still required

Rename old `kaosgdd-brain` to transitional `kaosgovernor-legacy-api` during the H3 move if
it still has unported deterministic API duties. Remove `kaosgovernor-legacy-api`, any
remaining main personal web, adapter, edge, or notification containers only
after their KaosGovernor replacements have passed the observation period.
Family KaosGDD is retained.

## Production Cutover Rules

- Never move PACS or DICOM as part of this plan.
- Never change a backend version during the same window as its data migration.
- Never allow old and new schedulers to write the same generated object concurrently.
- Never run two mail pollers without shared deduplication state.
- Never run two fax intake consumers without source-level idempotency.
- Every generated write carries a stable idempotency key.
- Every destructive or external-send operation is auditable.

## Minimum Observation Periods

Suggested minimums before deletion of old components:

- stateless UI/edge route: 48 hours
- Memos/Radicale data migration: 7 days
- scheduler/generated calendar writer: two complete recurrence cycles or 14 days
- mail poller: 7 days
- fax intake/outbound: successful live inbound and outbound tests plus 7 days
- AI write capability: evaluation pass plus 14 days of confirmed operation

### Optional Phase 10: RK1 worker pool

- Keep all RK1 nodes outside the required request path.
- Add only rebuildable background jobs with explicit queues and timeouts.
- Retry failed or low-confidence worker results on H4.
- Do not move Governor, Radicale, Memos, or family availability onto RK1.

## Completion Criteria

The migration is complete only when:

- all authoritative data has a tested backup and restore procedure
- Governor owns deterministic orchestration
- KaosBrain has only scoped Governor tools
- KaosAI/OpenClaw has no direct Governor or backend credentials
- Family AI has only family-scoped Governor tools
- office critical services operate during home/H4 outages
- Discord, Governor, native-app, or manual replacements are verified before KaosTelegram retirement
- the old Brain and bridge containers are stopped, archived, and removable without losing rollback documentation
