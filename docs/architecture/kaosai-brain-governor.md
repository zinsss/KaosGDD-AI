# KaosAI, KaosBrain, and KaosGovernor

KaosGDD separates language intelligence, request guarding, and authoritative
state changes.

Runtime paths are defined in
[Runtime Layout](./runtime-layout.md). In short, project-owned services live
under `/srv/kaosgdd/{kaosai,kaosbrain,kaosgovernor}`, while ready-made backends
such as Radicale, Memos, and Vaultwarden keep their own service names.

## Roles

```text
KaosAI
  understands language and drafts structured plans

KaosBrain
  owns Discord context, adapts plans, validates safety, and calls Governor

KaosGovernor
  owns confirmations, audit, durable operations, and writes to sources of truth
```

KaosAI is not a source of truth and does not receive Governor credentials.
KaosBrain is the adapter and guard. KaosGovernor is the authority.

## Request Flow

```text
Discord user message
  -> KaosBrain receives actor/channel/context
  -> KaosAI returns a strict plan
  -> KaosBrain Guard validates and adapts the plan
  -> KaosGovernor creates a proposal or serves a read-only tool result
  -> user confirms risky writes
  -> KaosGovernor writes and audits
```

## Plan Contract

KaosAI plans are small JSON objects:

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

KaosAI plans must not include backend object identifiers such as
`collectionId`, service URLs, tokens, shell commands, or restart commands.
KaosBrain derives internal IDs from its own configuration when needed.

The guard rejects system, shell, Docker, database, service restart, and any
unknown intents.

## Guard Rules

KaosBrain Guard is deterministic code. It:

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

The guard does not invent intent. If the plan is missing required fields or
cannot be adapted safely, Brain must ask again or fall back to deterministic
parsing.

## Authority Boundary

KaosAI may plan. It must not call Governor.

KaosBrain may adapt and validate. It owns the Governor tool client token but
does not own authoritative application data.

KaosGovernor validates again before writing. Radicale, Memos, Paperless,
HylaFAX, and other native services remain the sources of truth for their
domains.
