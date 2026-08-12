# Migration Plan

## Objectives

- Build the new H4/Turing Pi platform beside production.
- Keep PACS, DICOM, Paperless, RustDesk, and HylaFAX stable at the office.
- Move deterministic orchestration before enabling AI writes.
- Preserve all Radicale and Memos data.
- Migrate from Telegram to Discord incrementally.
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

Move Radicale, Memos, web edge, and then the unchanged Brain implementation to RK1 hosts before refactoring Brain into Governor.

Advantages:

- validates hardware and networking early
- separates office services sooner

Disadvantages:

- moves infrastructure and application behavior at the same time
- may require temporary ARM packaging of legacy Brain code
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

### Phase 1: Prepare Hardware and Base Networking

- Install RK1 operating systems on NVMe.
- Set fixed internal names and Tailscale identities.
- Update Turing Pi BMC credentials and firmware.
- Configure time synchronization, SMART monitoring, log limits, and host backups.
- Create empty Compose projects with health checks only when implementation starts.

No production service moves in this phase.

### Phase 2: Governor Foundation on RK1-1

- Implement Governor API, PostgreSQL migrations, audit, idempotency, operation status, and confirmation tokens.
- Run only read tools against production adapters initially.
- Add shadow comparison tests against the current Brain.
- Do not expose Governor publicly.

Rollback: stop RK1-1. Existing Brain remains authoritative.

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

### Phase 4: Radicale and Memos to RK1-3

Current production locations at planning time:

- Radicale data: `/srv/kaos/data/radicale`
- Radicale config/users: `/srv/kaos/config/radicale`
- Memos data: `/srv/kaos/data/memos`

Procedure:

1. Pin the exact source versions and confirm ARM64 images.
2. Prepare destination NVMe/SATA storage and permissions.
3. Take a verified backup and initial online copy.
4. Stop all Radicale/Memos writers, including Brain/Governor adapters and custom frontends.
5. Stop Radicale and Memos.
6. Perform a final archive-preserving `rsync` with numeric ownership.
7. Compare file inventory and cryptographic checksums.
8. Start the same application versions on RK1-3.
9. Test every user, collection, event, task, journal, memo, tag, resource, create, and edit path.
10. Switch one route at a time.
11. Keep original containers stopped and original data untouched through the observation period.

Memos SQLite WAL files require a clean stop before the final copy. Radicale configuration must move with collection data so users and rights are preserved.

Rollback:

- stop RK1-3 services
- restore original routing
- restart original services against untouched original data
- reconcile only writes accepted after cutover, if any

### Phase 5: Web Edge to RK1-4

- Deploy main and Family KaosGDD UIs.
- Deploy custom Memos UI.
- Deploy Caddy and one cloudflared connector.
- Route to Governor, Family AI, and RK1-3 through private addresses.
- Move hostnames one at a time.
- Keep native CalDAV requirements separate from interactive Cloudflare Access policy.

Rollback: restore the individual Caddy/tunnel route to the office host.

### Phase 6: Family AI on RK1-2

- Start with a constrained 4B model and one concurrent request.
- Add family-only Governor tools.
- Embed chat in Family KaosGDD.
- Add SSE response streaming, durable family chat messages, and Web Push.
- Test Korean date/time and Rouny commands against a fixed evaluation set.
- Keep all calendar/task writes confirmed until measured reliability is acceptable.

Failure must affect only AI chat, not Family KaosGDD or native services.

### Phase 7: KaosBrain on H4

- Deploy OpenClaw and the local model.
- Use a new Discord bot during migration.
- Register only the KaosGovernor MCP server.
- Deny shell, SSH, Docker, database, filesystem, and elevated tools.
- Start with Memos read/search, then use the same domain order as Governor.
- Benchmark 7-9B and 14B candidates using real Korean Kaos commands.

### Phase 8: Telegram to Discord

- Create minimal private Discord channels: `#kaos`, `#inbox`, and `#system`.
- Dual-deliver non-destructive notifications first.
- Verify document, mail, fax, confirmation, and cleanup interactions.
- Move commands only after delivery is reliable.
- Retire Telegram workflows individually.
- Keep KaosTelegram service control until an explicitly hardened replacement exists.

### Phase 9: Reduce the Office H3+

Target services that remain:

- KaosPACS and KaosPACS-AIO
- Paperless
- Stirling-PDF
- RustDesk
- HylaFAX and local Fax Connector
- Tailscale
- internal reverse proxy only if still required

Remove old Brain, web, adapter, edge, or notification containers only after their replacements have passed the observation period.

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

## Completion Criteria

The migration is complete only when:

- all authoritative data has a tested backup and restore procedure
- Governor owns deterministic orchestration
- KaosBrain has only scoped Governor tools
- Family AI has only family-scoped tools
- office critical services operate during home/H4 outages
- Discord workflows are verified before Telegram retirement
- the old Brain and bridge containers are stopped, archived, and removable without losing rollback documentation
