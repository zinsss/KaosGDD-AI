# Personal and Family KaosGDD Portal

Shared mobile-first KaosGDD portal. Hostname selects the personal or Family
profile; authoritative scope remains server-controlled.

The frontend remains static and keeps mock fallback data, while production
calendar/task operations go through the server-side calendar adapter.

## Routes

The personal profile uses one native main-menu selector so its growing route
list remains usable on iPhone and desktop:

- Agenda — `#/today`
- Calendar — `#/calendar`
- Tasks — `#/tasks`
- Memos — `#/memos`
- Documents — `#/documents`
- Fax — `#/fax`
- Mail — `#/mail`
- Utils — `#/services`
- Settings — `#/settings`

Fax and Mail currently show an explicit transition notice until their scoped
PWA read APIs are connected. Documents exposes its existing page and reports
the current API availability.

Stable calendar links:

- `#/calendar?date=YYYY-MM-DD` selects a calendar day for PWA/Shortcut links.
- `#/calendar?weather=YYYY-MM-DD` opens the existing detailed-weather popup.

Family retains its existing direct navigation and family-only routes.

## Boundaries

Data enters the UI through adapter-shaped functions in `app.js`. Calendar and task reads/writes use `/api/calendar/*`; mock data remains a local fallback when the adapter is unavailable.

Family Rouny templates use `/api/rouny/templates`, owned by KaosGDD Brain.
The browser keeps an offline local cache and sends revision-checked full-document
writes. A pre-Brain local timetable migrates automatically only while the server
document is empty; a fresh browser's generated Basic template is not uploaded
until the user saves it.

Rouny rejects an end time that is not later than its start time. Same-day
overlaps are highlighted in the editor but remain valid after explicit save
confirmation, because parallel classes can be intentional.

Future adapters:

- Calendar and task data -> Radicale adapter
- Documents -> Paperless adapter
- Notes and knowledge -> Memos

## Source Layout

This directory is the canonical shared static web root for `kaosgdd.net` and
`family.kaosgdd.net`; hostname selects the personal or family profile.
Do not keep a second nested copy such as `apps/family-portal/app/`; nginx serves
the files from the root of this directory.

Deploy through the H3 backend helper:

```bash
./deploy/h3-backend/kaos-h3 family-portal-sync
```

## Localization

Main KaosGDD uses the English fallback copy in `app.js`. All Family Korean UI copy is collected in `translations.js`.

Edit translation values only; keep dictionary keys and `{placeholder}` names unchanged. Bump the `translations.js` query version in `index.html` when deploying revised copy.
