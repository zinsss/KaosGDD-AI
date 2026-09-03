# Kaos Feed Command Interface

Decision date: 2026-09-03

Status: accepted as target design; implementation not started in this document.

## Decision

The personal `kaosgdd.net` PWA should evolve from separate pages into a
command-feed console. The feed may look conversational, but its main control
surface is openable cards, menus, buttons, and forms rather than a plain chat
box.

This replaces the assumption that Discord or Telegram must be the main
communication gateway. Discord may remain as a fallback `#brain` topic during
transition, but daily Kaos control should live in the PWA.

## Interface Model

```text
Kaos Feed
  timeline of system/domain cards
  openable command menus
  structured confirmation cards
  optional short text input for Ask Kaos
```

The key rule is:

```text
Chat is the container.
Cards and buttons are the control surface.
```

Examples:

```text
Morning Digest card
  [ Open Agenda ] [ Weather ] [ Tasks ] [ Documents ]

Fax Received card
  [ Open PDF ] [ Send To Documents ] [ Acknowledge ]

Document Inbox card
  [ Review Metadata ] [ Apply ] [ Open Paperless ]

System Attention card
  [ Full Status ] [ Plan Update ] [ Open #brain fallback ]

Task Proposal card
  [ Create ] [ Edit ] [ Cancel ]
```

The feed should not force every operation through free text. Most daily actions
should remain deterministic button/form operations.

## Ownership

```text
PWA Kaos Feed
  renders cards, buttons, forms, receipts, and deep links

KaosGateway / Governor API
  accepts structured UI commands and returns structured card data

KaosGovernor
  validates actor, scope, policy, confirmation, idempotency, and audit

KaosBrain
  interprets ambiguous/free-text requests only when useful

KaosBrain-OpenAI
  optional OpenClaw/OpenAI provider for Brain reasoning

Domain adapters / MacBridge
  perform approved operations against Radicale, Memos, Paperless, HylaFAX,
  mail, system runbooks, iMessage, Calendar/Reminders mirrors, or macOS apps
```

## Request Flows

### Deterministic button action

```text
User taps [ Complete Task ]
  -> PWA sends structured task.complete request
  -> Governor validates and applies confirmation policy
  -> Governor calls task domain adapter
  -> PWA receives receipt card
```

No Brain or OpenAI call is required.

### Openable command menu

```text
User taps global +
  -> PWA opens page-aware command menu
  -> user picks Add Task / Upload Document / Send Fax / System Status
  -> PWA opens the exact command card/form
```

The menu is UI state only. It does not authorize mutations.

### Ambiguous natural-language request

```text
User types "move unfinished non-clinic tasks to Monday"
  -> PWA sends Ask Kaos request
  -> KaosBrain interprets and drafts structured proposal
  -> Governor validates proposal and decides confirmation requirement
  -> PWA renders confirmation card
  -> final approved write goes through Governor
```

### Alert deep link

```text
Pushover: "Fax received."
  -> tap opens exact PWA feed/card route
  -> card fetches current state from Governor
  -> user acts from structured buttons if needed
```

## Card Types

Initial useful cards:

- daily digest
- agenda/day summary
- task proposal
- task due/overdue
- document inbox item
- document metadata review
- fax received/sent/failed
- unread mail batch
- supplies quick list
- memo quick capture/result
- system status/maintenance
- MacBridge/iMessage triage, if added later

## Data Contract

Feed cards should be explicit JSON objects, not rendered HTML blobs from Brain.

Minimum shape:

```json
{
  "id": "card-id",
  "type": "document.metadataReview",
  "title": "Review document metadata",
  "state": "pendingConfirmation",
  "summary": "Title and tags are ready to apply.",
  "actions": [
    {"id": "apply", "label": "Apply", "kind": "confirmingMutation"},
    {"id": "edit", "label": "Edit", "kind": "form"},
    {"id": "cancel", "label": "Cancel", "kind": "dismiss"}
  ],
  "links": [
    {"label": "Paperless", "href": "https://paperless..."}
  ]
}
```

Brain may draft the proposal behind a card, but Governor owns the card state,
confirmation requirement, action idempotency, and final receipt.

## Relationship to Existing Pages

The existing pages remain useful:

- Agenda
- Calendar
- Tasks
- Supplies
- Memos
- Documents
- Fax
- Mail
- Utils
- Settings

The feed should not replace them immediately. It should become a top-level
command/log view that opens exact existing pages or embeds focused command
cards. The current page-specific `+` behavior can become the first command-menu
primitive.

## Notification Relationship

Pushover remains the immediate Apple Watch alert layer. It should not carry
large details or action complexity.

Preferred pattern:

```text
Pushover short text
  -> exact PWA card/deep link
  -> Governor-backed structured action
```

Examples:

- `Good Morning.`
- `Fax received.`
- `Fax send failed.`
- `KaosBrain auth renewal.`
- `System maintenance required.`

## Security Rules

- Do not let PWA cards execute arbitrary shell, JavaScript, SQL, or generated
  model commands.
- Do not store authoritative state only in browser storage.
- Do not let Brain-generated text define executable action targets.
- Destructive or external-send actions require Governor confirmation policy.
- Action IDs must be scoped, expiring, and idempotent.
- MacBridge or system-operator actions remain behind Governor, not direct PWA
  access.
- PWA cards may display links to Discord `#brain`, Paperless, Memos, or other
  upstream UIs, but those links do not replace Governor authorization.

## Migration Path

1. Define read-only feed/card API shape.
2. Add a `Kaos Feed` route to the personal PWA.
3. Start with existing read-only sources:
   - daily digest state
   - mail unread marker
   - Documents Inbox
   - failed fax attention
   - system status
4. Convert current page-specific `+` menu into reusable command-card opening.
5. Add confirmation-card rendering for existing governed mutations.
6. Add optional Ask Kaos text input only after deterministic cards are useful.
7. Add Pushover deep links into exact cards.
8. Retire direct Discord operational surfaces only after feed replacements pass
   production observation.

## Non-Goals

- Do not build a Discord clone.
- Do not make OpenClaw or KaosBrain the action executor.
- Do not route ordinary button actions through an LLM.
- Do not replace existing domain pages in the first slice.
- Do not use browser local storage as the authoritative feed log.
- Do not remove Discord fallback until PWA feed, Pushover links, and Governor
  workflows are observed in production.
