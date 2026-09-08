# Current Brain Conversion Inventory

> 2026-09-08 update: H4 KaosBrain and the H3 Governor replacements are active.
> The old KaosGDD checkout remains a rollback/reference source only. The two
> legacy Governor containers are stopped and are retirement candidates under
> the [consolidation inventory](consolidation-inventory.md). The production fax
> bridge source belongs to this repository under `apps/fax-bridge`.

The existing `zinsss/KaosGDD` `apps/brain` implementation is no longer a live
production service. It was renamed to transitional
`kaosgovernor-legacy-api` during migration; the rename itself was not evidence
of replacement. The stopped service and database may retire only after their
remaining rollback/data gate is closed.

## Retain and Convert

| Current area | Planned destination | Notes |
| --- | --- | --- |
| Calendar upstream adapter | `governor/calendar` and `adapters/radicale` | Preserve VEVENT/VTODO compatibility and ETag behavior |
| Caregiver summary/upstream | `governor/calendar` or family domain extension | Keep deterministic calculations |
| Event presets | `governor/calendar` | Convert local/preset rules into typed calendar rules |
| Recurring tasks | `governor/calendar` plus `scheduler` | Calendar calculates; Scheduler triggers |
| Generated system calendar | `governor/calendar` | Holidays, market days, claim days, precedence rules |
| Supplies | Governor domain module or calendar VTODO capability | Preserve Radicale as authoritative list where retained |
| Memos relay/archive | `governor/memos` | Memos remains authoritative |
| Paperless/Stirling/document store | `governor/inbox` and adapters | Preserve source-key deduplication and temporary cleanup |
| HWP handoff | Retire or optional Inbox adapter | Prefer Polaris for manual use unless automation is needed |
| Mail notifier/archive/organizer | `governor/mail` | Governor API/worker owns the current Naver IMAP workflow; Discord presentation is transitional |
| Fax notifier/outgoing/intake/archive | `governor/fax` plus office Fax Connector | HylaFAX remains transport authority |
| Notification router | `governor/notifications` | PWA/domain archives hold detail; durable Pushover alerts remain minimal while native iOS owns task reminders; Discord delivery is transitional |
| Telegram access/transient utilities | Retire with KaosTelegram | Reimplement only useful dedupe/cleanup semantics inside Discord/Governor; do not migrate Telegram service state |
| Ledger | Separate Governor domain module if still required | Preserve deterministic arithmetic and XLSX import/export |
| Rouny store | `governor/calendar` | Calendar domain owns timetable rules and changes |
| Database migrations | New Governor migrations | Migrate data through explicit scripts, not manual SQL edits |
| Existing tests | Contract and module tests | Port tests before moving production ownership |

## Retain Outside Governor

- KaosPACS and DICOM storage
- Paperless storage and OCR
- Radicale collections
- Memos database and resources
- HylaFAX spool and modem configuration
- Tailscale networking
- Caddy/cloudflared edge configuration until the H3+ web-edge cutover
- production backup scripts until replacement backups are proven

## Retire Only After Verified Replacement

- transitional `kaosgovernor-legacy-api` containers after their deterministic modules are absorbed into KaosGovernor
- current Brain PostgreSQL
- KaosTelegram containers, bot tokens, bot state, and workflow presentation
- obsolete notification providers
- custom RHWP service if Polaris fully covers the remaining workflow
- old calendar adapter container
- legacy copy of the fax bridge in the old KaosGDD checkout, after the
  `apps/fax-bridge` deployment passes its live observation gate

Retirement requires a verified replacement, data reconciliation, rollback
instructions, and an observation period. A renamed module is not sufficient
evidence.
