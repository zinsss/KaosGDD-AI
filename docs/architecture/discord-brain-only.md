# Discord Brain-Only Target

Decision date: 2026-08-30

Status: accepted; migration not yet complete.

This decision supersedes earlier plans that made several Discord channels the
primary personal UI. Discord's final Kaos role is one private `#brain` topic
for persistent conversation with KaosBrain. Direct task, calendar, supplies,
Memos, document, mail/fax, notification, alert, and administration channels
are transitional and will retire after their replacements pass production
observation.

## Target

```text
Discord #brain -> KaosDiscoord -> KaosBrain -> KaosGovernor
                                      |              |
                                      |              +-> domain services
                                      +-> read/answer     Radicale / Memos /
                                                         Paperless / HylaFAX

Personal/Family PWAs / Shortcuts / optional Scriptable -> KaosGovernor
Pushover <- Governor notification outbox
Native CalDAV clients / Memos PWA / Paperless PWA -> authoritative services
```

The `#brain` topic may present Brain answers, structured proposals,
confirmations, operation receipts, and files explicitly requested in that
conversation. It is not the archive or notification engine for other domains.

## Replacement Matrix

| Retiring Discord surface | Target replacement | Authority |
| --- | --- | --- |
| Tasks and task acknowledgements | Personal KaosGDD PWA; scoped Shortcuts; native Reminders remains a sync/notification client | Radicale VTODO through Governor/native CalDAV |
| Calendar and agenda | Personal KaosGDD PWA; scoped deep links; native Calendar remains a sync/notification client | Radicale VEVENT |
| Supplies | Personal KaosGDD PWA and scoped Shortcut actions | Dedicated Radicale VTODO collection |
| Memos capture/search | Personal KaosGDD PWA with authoritative Memos links; Shortcuts; `Ask Kaos` in `#brain` | Memos |
| Document inbox/search | Personal KaosGDD PWA; Paperless PWA for advanced operations; Share Sheet Shortcut; `Ask Kaos` | Paperless |
| Mail notification/organizer UI | Minimal Pushover alerts; on-demand `#brain` query; service-backed organizer state | Naver IMAP and Governor state |
| Fax notification/intake UI | Personal KaosGDD PWA; minimal Pushover final-state alerts; Share Sheet/Shortcut or `#brain` send flow | HylaFAX and Governor operation records |
| Daily digest | Minimal `Good Morning.` Pushover alert; detail on demand in the retained `#brain` topic or mobile UI | Governor aggregate reads |
| System/maintenance alerts | Minimal Pushover alerts; detail on demand in `#brain` or settings/admin UI | Governor health/audit state |
| Service administration | Personal KaosGDD admin view and authenticated governed `#brain` operations | Governor health state and restricted host executors |

Pushover remains intentionally simple and text-only for the Apple Watch. It is
not a static UI or source of truth. Native Calendar and Reminders notifications
remain authoritative for events and tasks.

## Runtime Consequence

The current H3 service/container retains the transitional
`kaos-governor-discord` name, but its canonical source package and executable
are `integrations/discoord` and `kaosdiscoord`. That process also starts
schedulers, polling, Pushover delivery, health/tool routes, and domain adapters.
The Discord gateway cannot simply be stopped. First move those non-Discord
lifecycles behind a Governor-owned runtime entry point. Keep the same
modular-monolith deployment unless a separate process is operationally
justified; this decision does not require microservices.

H4 retains the KaosBrain Discord identity and the `#brain` topic. H3's
operational Discord identity and direct channel surfaces retire after the
worker split and replacement gates complete.

## Retirement Sequence

1. Freeze new features for direct Discord channels. Only safety, audit,
   compatibility, and retirement work continues there.
2. Inventory each active channel, persistent view, scheduler, notification,
   archive dependency, and retained Discord message/history requirement.
3. Preserve the personal KaosGDD PWA and finish scoped mobile APIs, stable PWA
   deep links, and the first useful Shortcut flows.
4. Verify Memos and Paperless PWA access and their iOS capture/search paths.
5. Move Pushover, mail/fax polling, daily digest, maintenance checks, and other
   workers out of the Discord gateway lifecycle.
6. Disable direct channel intake one domain at a time while retaining rollback
   configuration and observing the replacement.
7. Export or deliberately retain required Discord history before deleting any
   channel. Discord history must never be treated as the only mail/fax or
   document archive.
8. Disconnect and retire the H3 operational bot only after `#brain` on H4 can
   still call Governor and all non-Discord workers run independently.

## Gates

A direct Discord surface may retire only when:

- its authoritative backend and backup are identified;
- the replacement supports the required read and write operations;
- destructive actions use Governor validation and confirmation policy;
- alerts reach Pushover or the authoritative native app as designed;
- normal production use has been observed;
- rollback does not require restoring copied application data; and
- required Discord history has an explicit retain/export/delete decision.

## Non-Goals

- Do not remove `#brain` or the H4 conversational bot.
- Do not immediately delete channels, messages, bot state, or credentials.
- Do not move authoritative data into Shortcuts, Scriptable, Pushover, or
  Discord.
- Do not route ordinary deterministic mobile actions through an LLM.
- Do not rewrite Memos, Paperless, Radicale, HylaFAX, mail, or fax merely to
  retire a transport.
- Do not give Brain shell, SSH, Docker socket, secret, or direct host
  credentials in order to provide conversational system management.
