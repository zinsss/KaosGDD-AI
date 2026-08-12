# Current Brain Conversion Inventory

The existing `zinsss/KaosGDD` `apps/brain` implementation remains production
code until replacements are verified. During the H3 migration it may be renamed
from `kaosgdd-brain` to transitional `kaosgdd-gov` so operators do not confuse
it with the future H4 KaosBrain AI plane. That rename is not the replacement;
its deterministic modules still need to be ported into KaosGovernor before the
legacy service and database can be retired.

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
| Mail notifier/archive/organizer | `governor/mail` | Ported to Discord with unchanged Naver IMAP authority; retire legacy workers only after live verification |
| Fax notifier/outgoing/intake/archive | `governor/fax` plus office Fax Connector | HylaFAX remains transport authority |
| Notification router | `governor/notifications` | Replace Telegram/Pushover/ntfy paths with Discord/Web Push as approved |
| Telegram access/transient utilities | Discord interaction and transient cleanup utilities | Retain dedupe and cleanup semantics, not Telegram-specific assumptions |
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

- transitional `kaosgdd-gov` containers after their deterministic modules are absorbed into KaosGovernor
- current Brain PostgreSQL
- Telegram workflow presentation
- obsolete notification providers
- custom RHWP service if Polaris fully covers the remaining workflow
- old calendar adapter container
- old fax bridge implementation

Retirement requires a verified replacement, data reconciliation, rollback
instructions, and an observation period. A renamed module is not sufficient
evidence.
