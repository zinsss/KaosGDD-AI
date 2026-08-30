# Target Architecture

The detailed host, service-placement, interaction, security, backup, and
migration decisions are maintained in the
[H4 Ultra + H3+ production plan](h4-h3-production-plan.md).

Implementation phases and current progress are tracked in the
[Brain / Governor / Discoord / iOS migration plan](../migration/brain-governor-discoord-ios-plan.md).

## Overview

```text
Discord #brain only   Shortcuts / Scriptable       Family KaosGDD PWA
   |                    |                           |
   v                    |                           |
KaosDiscoord            |                           |
   |                    |                           |
   +---- deterministic calls ----------------------+
   |                    |                           |
   +-> KaosBrain on H4 <-+ when interpretation is needed
          |              |                           |
          +--------------+---------------------------+
                         |
                         v
                KaosGovernor on H3+ backend
                    |
        +-----------+------------+
        |           |            |
        v           v            v
     Radicale      Memos      Office services
        ^           H3+       Paperless/HylaFAX
        |
iOS Calendar and Reminders
(personal, family, supplies)
```

KaosBrain communicates with backends only through KaosGovernor. KaosDiscoord
is retained only for the private Discord `#brain` conversation. Shortcuts,
Scriptable, and the family UI may call Governor directly for deterministic
operations. Family AI receives a separate family-scoped Governor credential.

Native clients may still use service-native interfaces:

- iOS Calendar and Reminders use Radicale over CalDAV.
- Personal events, tasks, and supplies use those native iOS apps as their
  primary UI.
- Family KaosGDD remains the custom family UI and uses Governor/service APIs.
- Memos may be opened through its native web UI when direct editing is useful.
- Paperless users may use the Paperless UI.
- HylaFAX continues locally at the office if home AI infrastructure is unavailable.

Nextcloud is not part of the target backend. Radicale remains the CalDAV
authority, Memos remains the memo authority, and SFTPGo remains the planned
purpose-built file transfer service where needed.

KaosGDD is the umbrella project. Under it, KaosBrain owns language
interpretation and guarded structured action proposals, KaosGovernor owns
deterministic orchestration, and KaosDiscoord is the replaceable Discord
transport. KaosAI remains the optional model/planner implementation used by
Brain. Ready-made backend services keep their native
operational identities, such as Radicale, Memos, Vaultwarden, SFTPGo, Caddy,
and cloudflared, rather than being renamed to `kaosgdd-*`.

No main personal KaosGDD web application is planned. Its repository may remain
as reference, and a new personal UI may be considered later only when native
iOS clients and Discord leave a concrete workflow unmet.

## KaosGovernor

KaosGovernor is a modular monolith with one repository and database but several runtime processes.

Its transport-neutral operation lifecycle starts at
`kaos_governor.operations.GovernorOperations`. Transports submit normalized
requests there for idempotency, confirmation, audit-state transitions, and
completion. Domain execution is being moved behind this boundary
incrementally; compatibility routes remain available during the migration.

```text
KaosGovernor
├── KaosScheduler
├── KaosCalendar
├── KaosMemos
├── KaosMail
├── KaosFax
├── KaosInbox
├── KaosNotifications
└── KaosAudit
```

### KaosScheduler

Owns time, not domain policy:

- one-time and recurring jobs
- delayed follow-ups and snoozes
- reminder triggers
- missed-job recovery after downtime
- daily and weekly summaries
- scheduled AI turns
- retries, leases, expiration, and deduplication

A scheduled AI turn stores an explicit purpose, actor scope, target agent, allowed tools, delivery target, expiry, and idempotency key. It does not depend solely on old conversation context.

### KaosCalendar

A complete calendar and task domain capability, not a thin CalDAV client:

- calendar and task rules
- preferences and temporary exceptions
- event/task validation and conflict detection
- standard and custom recurrence behavior
- claim day, market day, and holiday generation
- settings-managed weather location and imported public holiday sources
- Rouny scheduling
- reminder defaults
- VEVENT/VTODO serialization
- ETag-safe Radicale writes

KaosScheduler wakes calendar jobs. KaosCalendar decides what the job means and whether a write is valid.

### KaosMemos

- Memos search, retrieval, creation, and update
- tag and visibility validation
- canonical Memos API adapter
- optional rebuildable semantic index references

Memos remains the source of truth. Embeddings and AI summaries are disposable derivatives.

### KaosMail

- IMAP polling
- folder selection and mail rules
- deduplication
- attachment intake
- notification delivery and transport-specific inbox actions
- retry and read/delete/import operations

AI may summarize collected mail but does not own polling or mailbox state.

### KaosFax

- inbound/outbound fax operation records
- number and attachment validation
- confirmations
- status transitions and retries
- transport-neutral result presentation, including requested `#brain` output

Physical modem access remains in a narrow office Fax Connector beside HylaFAX.

### KaosInbox

- iOS Share Sheet and family file intake; requested `#brain` files only
- temporary upload lifecycle
- MIME, size, and duplicate validation
- Paperless import and metadata application
- optional Stirling-PDF operations
- cleanup after import, delivery, expiration, or cancellation

Mail attachments and faxes may create Inbox references without transferring ownership of their original workflows.

### KaosNotifications

- Pushover delivery for immediate personal text alerts
- requested `#brain` detail/receipts
- Family PWA chat delivery and Web Push
- quiet hours and category preferences
- retry/outbox handling
- deterministic fallback messages when AI is unavailable

### KaosAudit

Records meaningful operations rather than ordinary debug logs:

- actor and channel
- requested operation
- normalized parameters
- confirmation and approval state
- prior and resulting object versions
- backend object IDs
- success, failure, and retry history
- correlation and idempotency identifiers

## Runtime Processes

The H3+ backend should run one Governor image with separate commands where useful:

```text
governor-api
governor-worker
kaos-scheduler
kaos-mail-worker
governor-discord  # current compatibility process; target adapter is KaosDiscoord
governor-postgres
```

Modules remain in one codebase. Separate processes are used only for polling, scheduling, blocking connections, or failure isolation.

Office Kaos separately runs:

```text
kaos-fax-connector
```

## Data Ownership

| Data | Authority |
| --- | --- |
| Events, tasks, journals | Radicale |
| Memos and memo resources | Memos |
| Documents and metadata | Paperless |
| Fax transport and local fax queues | HylaFAX |
| Governor jobs, rules, confirmations, audit | Governor PostgreSQL |
| Conversation working context | KaosBrain or Family AI, non-authoritative |
| DICOM and PACS database | Existing office PACS services |

## Failure Behavior

- H4 failure removes main AI conversation but not scheduled deterministic services.
- Family AI failure removes family AI chat but not Family KaosGDD, Radicale, or Memos.
- Governor failure pauses orchestration while native services remain accessible.
- Web-edge failure removes web entry points while data services remain intact.
- H3+/H4 failure does not stop office PACS, HylaFAX, Paperless, or RustDesk.
- Office-to-home network failure queues fax events locally for later delivery.

## Optional RK1 workers

The Turing Pi 2 and RK1 nodes are not part of the required path. They may later
run rebuildable jobs such as embeddings, OCR post-processing, conversion, or
small-model batch work. Governor, Radicale, Memos, and normal family operation
must remain functional when every RK1 is offline.
