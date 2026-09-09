# Governor Notification Inbox and ChatGPT Delivery

Decision date: 2026-09-09

Status: Governor inbox, personal PWA, and read-only Shortcut API implemented;
ChatGPT app connection and hourly Scheduled Task pending production setup.

## Decision

All KaosGDD operational notifications have one durable source of truth in
KaosGovernor. ChatGPT, the personal PWA, and iOS Shortcuts are clients of that
inbox; none of them owns notification state.

```text
mail / fax / digest / maintenance producers
                    |
                    v
        Governor notification inbox
          |            |             |
          v            v             v
     personal PWA  iOS Shortcut  ChatGPT app
        + ACK        read-only     hourly monitor
```

The target has no Discord, Telegram, or Pushover notification dependency.
Pushover remains a reversible transition transport until ChatGPT mobile
delivery has completed an observation window without missed alerts.

## Durable State

The worker writes transport-neutral attention records to
`/data/notifications/inbox.json` whether or not Pushover delivery is enabled.
Each public record contains a non-secret opaque id, category, title, message,
priority, creation time, and acknowledgement state. Producer deduplication keys
and acknowledgement actors are not returned to clients.

Acknowledgement is separate from delivery. Opening or polling the inbox does
not silently clear an alert. Acknowledgement is idempotent, and acknowledged
records are retained as a bounded audit history.

## Client Contracts

### Personal PWA

```text
GET  /api/notifications
POST /api/notifications/<24-hex-id>/acknowledge
```

These same-origin routes require the verified personal Cloudflare Access
identity. The API facade supplies the powerful Governor credential only on the
server side. Family access is rejected. The main menu and KaosGDD title use the
existing quiet attention colors for pending and critical records.

### iOS Shortcut

```text
GET https://<H3_MAGICDNS_NAME>/shortcuts/notifications
Authorization: Bearer <IOS_SHORTCUTS_TOKEN>
```

The route is tailnet-only and read-only. It returns both structured `items` and
a `text` field ready for Quick Look or Show Result. It does not acknowledge,
delete, or mutate an item.

Suggested Shortcut actions:

1. `Get Contents of URL` with method GET and the bearer Authorization header.
2. Read `pendingCount`. If it is zero, show `No pending notifications.`
3. Otherwise show the returned `text` and offer `Open URL` for
   `https://kaosgdd.net/#/notifications`.
4. Acknowledge from the protected PWA after reviewing the item.

### ChatGPT Scheduled Task

Do not put the Shortcut or Governor bearer token in a ChatGPT task prompt or a
URL. ChatGPT must access a narrow read-only KaosGDD app/connector that returns
the same public inbox fields and cannot acknowledge or perform other Governor
operations.

After that app is connected, create one hourly monitoring task:

```text
Every hour, check my KaosGDD notification inbox through the connected KaosGDD
app. Notify me only when there are pending notification IDs that you have not
reported before, or when the inbox cannot be reached. Include priority, title,
message, and a link to https://kaosgdd.net/#/notifications. Stay silent when
nothing changed. Never acknowledge or modify an item.
```

ChatGPT mobile push must be enabled in ChatGPT Settings > Notifications. The
standard scheduled-task interval is hourly; do not simulate 30 minutes with
two overlapping tasks.

## Cutover

1. Deploy and verify Governor inbox, PWA, and Shortcut reads.
2. Connect the narrow KaosGDD ChatGPT app and run a synthetic low-priority test.
3. Observe ChatGPT and Pushover in parallel for seven days.
4. Disable Pushover without deleting its secrets or prior outbox state.
5. After a rollback window, remove the Pushover transport and credentials.

This workflow belongs to Governor and ChatGPT. n8n may monitor scheduled
workflow health, but it does not own notification records or acknowledgements.

Reference: [Scheduled tasks in ChatGPT](https://help.openai.com/en/articles/10291617).
