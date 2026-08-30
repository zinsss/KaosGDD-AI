# KaosBrain, KaosGovernor, and KaosDiscoord

KaosGDD separates language intelligence, deterministic authority, domain
execution, and transport concerns.

Runtime paths are defined in
[Runtime Layout](./runtime-layout.md). In short, project-owned services live
under `/srv/kaosgdd/{kaosai,kaosbrain,kaosgovernor}`, while ready-made backends
such as Radicale, Memos, and Vaultwarden keep their own service names.

The canonical phase and progress tracker is the
[Brain / Governor / Discoord / iOS migration plan](../migration/brain-governor-discoord-ios-plan.md).

## Roles

```text
KaosBrain
  understands language, reasons over context, and drafts guarded structured actions

KaosGovernor
  validates actions and owns confirmations, audit, operation state, and execution routing

KaosDiscoord
  owns Discord connection, IDs, attachments, controls, and response formatting

KaosGDD domain services
  execute operations and preserve each service's source of truth
```

KaosAI is the optional model/planner implementation inside the Brain role. It
is not a source of truth. Brain may read context and propose actions, but it
does not directly mutate Radicale, Memos, Paperless, HylaFAX, or Governor data.
Governor is the deterministic authority and does not depend on Brain or
Discord.

The current H4 package still contains Discord views around the Brain logic, and
the current H3 Discord package still hosts compatibility tool routes. Those
transport pieces will be isolated incrementally; they are not the target
ownership model.

## Request Flow

```text
Discord user message
  -> KaosDiscoord receives actor/channel/context
  -> KaosBrain interprets the request and returns a strict action
  -> KaosGovernor creates a proposal or serves a read-only tool result
  -> user confirms risky writes
  -> KaosGovernor routes the validated operation to a domain service and audits
  -> KaosDiscoord formats the result for Discord
```

Deterministic commands do not invoke Brain:

```text
Discord / task done
  -> KaosDiscoord parses the command
  -> KaosGovernor validates and executes the structured operation
  -> KaosDiscoord formats the result
```

## Plan Contract

Brain actions are small JSON objects. The current KaosAI planner uses this same
contract:

```json
{
  "intent": "task.update_due",
  "scope": "family",
  "parameters": {
    "taskTitle": "영이 큐시미아",
    "dueDate": "2026-08-24",
    "dueTime": "10:00"
  }
}
```

Allowed read-only intents:

- `today.get`
- `task.list_active`
- `task.list_completed`
- `memo.search`
- `document.search`

Allowed mutation intents:

- `task.create`
- `task.update_due`
- `task.edit`
- `task.complete`
- `task.delete`
- `task.reopen`
- `event.create`
- `memo.create`
- `memo.edit`
- `memo.delete`

Allowed scopes:

- `personal`
- `family`
- `supplies`

Allowed parameters:

| Intent | Parameters |
| --- | --- |
| `today.get` | none |
| `task.list_active` | none |
| `task.list_completed` | `query`, `start`, `end` |
| `memo.search` | `query` |
| `document.search` | `query` |
| `task.create` | `title`, `dueDate`, `dueTime` |
| `task.update_due` | `taskTitle`, `dueDate`, `dueTime` |
| `task.edit` | `taskTitle`, `title`, `memo`, `dueDate`, `dueTime`, `priority` |
| `task.complete` | `taskTitle` |
| `task.delete` | `taskTitle` |
| `task.reopen` | `taskTitle` |
| `event.create` | `title`, `startDate`, `endDate`, `allDay`, `memo` |
| `memo.create` | `content` |
| `memo.edit` | `query`, `content` |
| `memo.delete` | `query` |

Model-produced plans must not include backend object identifiers such as
`collectionId`, service URLs, tokens, shell commands, or restart commands.
Deterministic adaptation derives internal IDs from trusted configuration when
needed.

The guard rejects system, shell, Docker, database, service restart, and any
unknown intents.

## Guard Rules

The current Brain Guard is deterministic code. It:

- checks intent allowlists
- checks scope allowlists
- rejects unknown top-level fields and unknown intent parameters
- validates dates as `YYYY-MM-DD`
- validates times as `HH:MM`
- maps read-only plans to `ToolRequest`
- maps mutations to typed Governor proposal requests
- requires confirmation for all mutation intents
- strips due dates from supplies creates and edits
- rejects supplies due-date updates

The guard does not invent intent. If a plan is missing required fields or
cannot be adapted safely, Brain asks for clarification or falls back to a
deterministic parser.

## Authority Boundary

Brain may interpret, answer, and propose. It must not directly write a source
of truth.

Governor accepts structured requests from Brain and deterministic callers. It
must remain callable when Brain and Discord are unavailable.

KaosDiscoord owns no domain rules. Shortcuts and Scriptable likewise remain
clients and keep no authoritative state.

Governor validates before routing writes. Radicale, Memos, Paperless, HylaFAX,
and other native services remain the sources of truth for their domains.

## Migration Status

The Phase 1 operation-boundary slice was completed on 2026-08-30:

- `kaos_governor.operations.GovernorOperations` is the transport-neutral
  lifecycle boundary.
- Existing Brain tool mutation routes delegate operation submission,
  confirmation approval, completion, failure, and audit transitions to that
  boundary.
- Existing HTTP contracts, confirmation behavior, deployment processes, and
  domain adapters are unchanged.
- Pending normalized write payloads still live in process memory. PostgreSQL
  persistence is a later phase and is not implied by this boundary alone.
