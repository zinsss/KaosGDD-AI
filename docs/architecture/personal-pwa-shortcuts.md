# Personal KaosGDD PWA and iOS Shortcuts

Decision date: 2026-08-30

Status: accepted; selected-date navigation, the compact menu, the personal
Memos client repair, and the read-only Paperless browser are deployed. The
Memos/Paperless UI slice is awaiting normal user observation.

## Decision

Retain the existing personal KaosGDD web interface at `kaosgdd.net` as the
primary visual console. Evolve it as a mobile-first Home Screen web app instead
of replacing its calendar, tasks, colors, and related views with a second
Scriptable implementation.

The next interface direction is a PWA-native command feed: a chat-like timeline
of openable cards, menus, buttons, and confirmation forms. See
[Kaos Feed Command Interface](kaos-feed-command-interface.md). The feed may
include an optional Ask Kaos text box, but normal daily control should be
buttons and structured cards rather than free-form chat.

iOS Shortcuts is the system-integration layer for Action Button menus, Siri,
Share Sheet capture, quick creation, and deep links. Scriptable remains
optional for a widget or a focused interface that Shortcuts and the PWA cannot
provide well; it is not a required container for the calendar.

This decision supersedes the earlier assumption that no personal KaosGDD web
application would be retained. The concrete workflow gap is that native iOS
Calendar and Reminders are useful synchronization and notification clients but
are not the preferred daily interface.

## Interaction Model

```text
KaosGDD PWA
  stable visual UI for Today, calendar, tasks, supplies, fax, Memos, documents,
  plus a future Kaos Feed of command cards and receipts

iOS Shortcuts
  Action Button, Siri, Share Sheet, quick capture, deterministic actions,
  and links to an exact PWA route or authoritative upstream item

Pushover
  immediate minimal alerts and Apple Watch delivery

iOS Calendar and Reminders
  optional native UI; continue CalDAV synchronization and native scheduled
  notifications against Radicale

Discord #brain / Ask Kaos
  fallback natural-language reasoning, cross-domain questions, proposals, and
  receipts during migration
```

The PWA, Shortcuts, native CalDAV clients, and Brain are parallel clients. None
of them becomes an authoritative data store.

## Domain Authority

| Personal surface | Source of truth | Initial PWA responsibility |
| --- | --- | --- |
| Calendar | Radicale VEVENT | Today/month/day views and governed event actions |
| Tasks | Radicale VTODO | Active/completed views and governed task actions |
| Supplies | Dedicated Radicale VTODO collection | List and focused supply actions |
| Fax | HylaFAX plus Governor operation/archive state | Send, recent status, and exact-result links |
| Memos | Memos | Embedded Kaos Memos client for recent/search/create/edit and authoritative storage |
| Documents | Paperless-ngx | Recent/search/detail/OCR and links to the authoritative document |

Advanced service-specific workflows may open the upstream Memos or Paperless
PWA. KaosGDD does not copy their databases or reimplement every administration
screen.

The embedded Memos surface is the existing Kaos-built `kaosgdd-memos-web`
client, not the upstream Memos application and not a new state store. Personal
and Family run separate client containers/configurations while both use the
profile-scoped, Cloudflare-verified Governor relay. Paperless uses a native
KaosGDD Documents page and a narrow read-only `/api/paperless/documents`
contract; its API token remains server-side.

## Personal and Family Isolation

The existing frontend may share calendar/task components and static assets
between the `main` and `family` profiles. Host identity, authenticated actor,
API scope, and server-side authorization decide which data is accessible.

- `kaosgdd.net` uses the personal profile, colors, navigation, and personal
  authorization.
- `family.kaosgdd.net` retains its family theme and family-only capabilities.
- Family credentials never unlock personal tasks, Memos, documents, fax,
  PACS, infrastructure, or administrative operations.
- A query parameter or browser-controlled profile value must never expand
  authorization scope.

## Shortcut Boundary

Shortcuts receives a separately scoped mobile credential. It never receives a
broad Governor token, OpenAI/OpenClaw credential, backend service password, or
CalDAV administrative credential.

Deterministic Shortcut actions call Governor directly. `Ask Kaos` is the only
normal Shortcut path that invokes Brain. Destructive operations and external
transmissions retain Governor confirmation policy.

Initial stable deep-link contract:

```text
https://kaosgdd.net/#/today
https://kaosgdd.net/#/calendar
https://kaosgdd.net/#/calendar?date=YYYY-MM-DD
https://kaosgdd.net/#/tasks
https://kaosgdd.net/#/supplies
https://kaosgdd.net/#/memos
https://kaosgdd.net/#/documents
```

Deep links select presentation state only. They do not authorize a mutation.

## Native iOS Relationship

Radicale remains authoritative regardless of which interface is visible. iOS
Calendar and Reminders may continue synchronizing in the background and may
retain native scheduled notifications even if their visual interfaces are
rarely opened. The PWA and Shortcut actions read or mutate the same objects
through Governor and ETag-safe adapters.

## Non-Goals

- Do not put authoritative state in browser storage, Shortcuts, or Scriptable.
- Do not embed the full PWA in Scriptable merely to hide that it is web-based.
- Do not duplicate the Family and personal frontend into unrelated codebases.
- Do not expose personal data through the Family hostname or family token.
- Do not replace Pushover with unreliable background PWA polling.
- Do not remove native CalDAV synchronization merely because the native UI is
  not preferred.

## Incremental Delivery

1. Stabilize read-only route and selected-date deep links.
2. Document Home Screen installation and Shortcut launch actions.
3. Expose scoped read APIs and deterministic create/update actions one domain
   at a time.
4. Add Share Sheet capture for Paperless and fax only after upload,
   confirmation, and cleanup contracts are tested.
5. Add the first read-only Kaos Feed/card API and render existing attention
   sources as cards.
6. Observe each PWA/Shortcut/feed replacement before retiring its Discord
   surface.

## Memos and Paperless UI Slice — 2026-08-31

Delivered:

- restored the existing personal Kaos Memos client on H3 instead of rebuilding
  or embedding the retired office service
- retained the working Family Memos client and route unchanged
- replaced the obsolete temporary-PDF queue screen with a KaosGDD-owned
  Paperless recent/search/paging/detail/OCR interface
- retained exact links to Paperless for advanced document operations
- added a narrow Governor Paperless read API protected by verified Cloudflare
  Access identity and restricted to the personal profile
- kept the Paperless token, Memos tokens, and OCR access out of JavaScript and
  Shortcuts

The Paperless slice is deliberately read-only. Upload, metadata changes, and
AI proposals will be added as governed operations with explicit confirmation
where required. Paperless remains authoritative; KaosGDD stores no document or
OCR copy.

The current Kaos Memos client supports its established create/edit/delete
workflow through the allow-listed Governor relay. A later hardening slice may
move those writes onto the durable Governor operation ledger without changing
the client or Memos authority.

Production observation gate:

- open Memos from the personal selector and confirm recent/search/edit behavior
- open Documents and confirm the 26-document Paperless list, search, one detail
  view, OCR rendering, paging, and the authoritative Paperless link
- confirm Family Memos behavior remains unchanged

Rollback requires no data migration: remove the personal Memos route/container,
restore the previous portal assets and Governor API image, and leave Memos and
Paperless data untouched.
