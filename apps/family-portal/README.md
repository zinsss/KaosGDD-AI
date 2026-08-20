# KaosGDD Mobile Shell

Mobile-first KaosGDD app shell.

This is the first app-shaped version after the mobile v1 prototype. The frontend remains static and keeps mock fallback data, while production calendar/task operations go through the server-side calendar adapter.

## Routes

- `#/today`
- `#/calendar`
- `#/tasks`
- `#/services`

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

## Deploy

The production test deployment is served from the existing KaosGDD portal nginx container under:

```text
/          main app
/app/
```

The old service launcher remains available as `/launcher.html`. The static prototype remains available as `/mobile-v1/`.

Deploy without copying the private checkout permissions onto the nginx web root:

```bash
rsync -rltp --chmod=Du=rwx,Dgo=rx,Fu=rw,Fgo=r apps/mobile-shell/ /srv/kaos/data/kaosgdd/portal/
rsync -rltp --chmod=Du=rwx,Dgo=rx,Fu=rw,Fgo=r apps/mobile-shell/ /srv/kaos/data/kaosgdd/portal/app/
```

## Localization

Main KaosGDD uses the English fallback copy in `app.js`. All Family Korean UI copy is collected in `translations.js`.

Edit translation values only; keep dictionary keys and `{placeholder}` names unchanged. Bump the `translations.js` query version in `index.html` when deploying revised copy.
