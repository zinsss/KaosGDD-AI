# H3 Worker Detachment

## Purpose

The H3 `kaos-governor-discord` process currently owns both the Discord gateway
and several background lifecycles. The gateway cannot be retired until every
non-Discord lifecycle has an independent owner. Each cutover must preserve one
writer, the current durable state, and a direct rollback.

## Current Lifecycle Inventory

| Lifecycle | Current owner | Discord coupling | Target owner | Migration order |
| --- | --- | --- | --- | --- |
| Pushover pending delivery | `GovernorBot` task | None; reads the shared notification outbox | `kaos-governor-worker` | 1 |
| Daily digest scheduling | `GovernorBot` task | Publishes a Discord message and controls before queuing Pushover | Governor worker with mobile/Brain detail | 2 |
| Naver mail polling | `GovernorBot` task | Poller callbacks render/send Discord mail and attachments | Governor worker with archive plus minimal Pushover | 3 |
| Fax lifecycle polling | `GovernorBot` task | `DiscordFaxTransport` consumes domain actions | Governor worker with durable archive plus minimal Pushover | 3 |
| Maintenance reminders | `GovernorBot` task | Sends Discord detail before Pushover | Governor worker with Pushover; detail queried on demand | 4 |
| Health and Brain tool HTTP routes | Discord process setup hook | Server is neutral, but status/refresh callbacks reference Discord surfaces | Governor API/worker runtime | 4 |
| Mail organizer schedule | `GovernorBot` task | Persistent Discord views and action messages | Governor service plus scoped mobile/Brain operations | 5 |
| Calendar/task/supplies refresh | `GovernorBot` tasks | Entirely direct-Discord presentation | Retire with those Discord surfaces | 6 |
| Task due repeat notifications | `GovernorBot` task | Discord acknowledgement buttons | Native iOS task notifications; then retire | 6 |
| Service-status refresh | `GovernorBot` task | Persistent Discord status messages and restart view | Governor health state plus Pushover and admin/Brain query | 6 |
| Paperless OCR tracking | Per-interaction Discord task | Restores and edits Discord prompts | Scoped mobile/Paperless workflow | 6 |

## Cutover Rule

Each lifecycle moves independently:

1. Add a new owner while it is disabled or queue-only.
2. Test ownership, state compatibility, health, and rollback.
3. Stop the old writer and start the new writer in the same guarded deployment.
4. Verify no duplicate action and no pending-state loss.
5. Observe production before moving the next lifecycle.

The first cutover moves only Pushover delivery. KaosDiscoord continues to
produce notification records, but in worker mode it only appends to the shared
outbox. `kaos-governor-worker` is the sole process allowed to deliver pending
records. A cross-process file lock protects the JSON outbox while the producer
and worker share it.

## Pushover Rollback

Stop `governor-worker`, set `PUSHOVER_DELIVERY_MODE=inline`, and recreate the
KaosDiscoord service with the retained rollback image. Pending records remain
in `/data/notifications/pushover.json`; the inline owner resumes delivery from
that same outbox.
