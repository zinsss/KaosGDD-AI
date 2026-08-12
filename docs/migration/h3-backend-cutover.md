# H3+ backend migration runbook

## Scope

The destination H3+ receives Governor first. Memos and Radicale move later in
separate, controlled write freezes.

The following remain on Office Kaos during this migration:

- KaosPACS, Orthanc, PACS PostgreSQL, MWL, and all DICOM data
- Paperless and its document archive
- HylaFAX, modem device, fax spool, and fax connector
- RustDesk
- Stirling-PDF unless a later explicit move is approved

## Phase 1: Governor side by side

1. Install the H3 deployment using `deploy/h3-backend/README.md`.
2. Keep Memos search pointed at the current Memos Tailscale address.
3. Keep H3 fax disabled; Office Kaos remains the fax worker.
4. Start Governor and verify `/health`, Discord, Memos search, and Naver mail.
5. Observe before stopping the old Governor writer or poller.

Do not run two Naver mail organizers or two fax consumers against the same
source without shared idempotency state.

## Phase 2: stage Memos and Radicale

Create destination directories:

```bash
sudo install -d -m 0770 -o "$USER" -g "$(id -gn)" \
  /srv/kaos/data/memos \
  /srv/kaos/data/radicale \
  /srv/kaos/config/radicale
```

Take application backups first. Perform an initial copy while services are
running only to reduce final downtime; that copy is not a valid cutover copy.

```bash
rsync -aHAX --numeric-ids --info=progress2 \
  kaos:/srv/kaos/data/memos/ /srv/kaos/data/memos/
rsync -aHAX --numeric-ids --info=progress2 \
  kaos:/srv/kaos/data/radicale/ /srv/kaos/data/radicale/
rsync -aHAX --numeric-ids --info=progress2 \
  kaos:/srv/kaos/config/radicale/ /srv/kaos/config/radicale/
```

## Phase 3: final write freeze

1. Disable routes and clients that can write Memos or Radicale.
2. Stop the source Memos and Radicale containers cleanly.
3. Confirm Memos stopped cleanly. Copy the database and any WAL/SHM files as
   one stable set; remove no database files manually.
4. Repeat all three `rsync` commands with `--delete` only after reviewing both
   source and destination paths.
5. Generate sorted SHA-256 manifests on both hosts and compare them.
6. Run `sqlite3 /srv/kaos/data/memos/memos_prod.db 'PRAGMA integrity_check;'`
   on the destination and require an `ok` result.

Example manifest command:

```bash
find /srv/kaos/data/memos -type f -print0 \
  | sort -z \
  | xargs -0 sha256sum > /tmp/memos.sha256
```

Use the same relative root on both machines before comparing manifests.

## Phase 4: guarded start and validation

```bash
cd /srv/projects/KaosGDD-AI
./deploy/h3-backend/kaos-h3 backends-preflight
./deploy/h3-backend/kaos-h3 backends-up
```

Validate before changing public or CalDAV routes:

- personal and family Memos users can authenticate
- memo counts, tags, resources, create, edit, and delete work
- all Radicale users and rights load
- personal/family calendars and task collections sync
- VEVENT, VTODO, VJOURNAL, recurrence, and ETags are preserved
- iOS Calendar and Reminders perform a full read/write round trip
- Governor live search returns existing personal memos

Switch one hostname or client endpoint at a time.

## Rollback

If validation fails before clients write to H3:

1. Stop destination Memos and Radicale.
2. Restore routing to Office Kaos.
3. Start the untouched source containers.

If destination writes were accepted, stop and reconcile them deliberately
before rollback. Never copy an active SQLite database backward over the source.

Keep source data untouched for at least seven days after successful cutover.
