# Governor Notification Inbox and ChatGPT Delivery

Decision date: 2026-09-09

Status: Governor inbox, personal PWA, read-only on-demand Shortcut API, and
personal PWA Web Push are implemented. Device enrollment and the seven-day
parallel observation with Pushover remain.

## Decision

KaosGDD attention notifications have one durable source of truth in
KaosGovernor. The personal PWA and iOS Shortcuts are clients of that inbox;
neither owns notification state. AI Task completion is the deliberate narrow
exception described below: its archive record is already the durable state, so
completion Web Push does not duplicate it in the attention inbox.

```text
mail / fax / digest / maintenance producers
                    |
                    v
        Governor notification inbox
          |                         |
          v                         v
     PWA + Web Push          iOS Shortcut
        + ACK              read-only, on demand
```

The target has no Discord, Telegram, ChatGPT polling, or Pushover notification
dependency. Pushover remains a reversible transition transport until PWA Web
Push has completed an observation window without missed alerts. A future
ChatGPT/MCP connection may query the inbox conversationally, but is not part of
notification delivery.

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
delete, or mutate an item. The Shortcut is deliberately retained as a live
on-demand check even after Web Push is enabled.

Suggested Shortcut actions:

1. `Get Contents of URL` with method GET and the bearer Authorization header.
2. Read `pendingCount`. If it is zero, show `No pending notifications.`
3. Otherwise show the returned `text` and offer `Open URL` for
   `https://kaosgdd.net/#/notifications`.
4. Acknowledge from the protected PWA after reviewing the item.

### PWA Web Push

Governor sends an event-driven Web Push when a new inbox record is created and
at least one personal device is subscribed. Enable or disable the current
device from the personal PWA Settings page; `Send test` performs a synthetic
low-priority delivery. On iPhone/iPad, KaosGDD must be installed on the Home
Screen and permission must be granted from that user-initiated Enable action.
The notification opens `https://kaosgdd.net/#/notifications`; review and
acknowledgement remain in the protected PWA. Lock-screen payloads are generic
category notices; mail, fax, phone, patient, and medical detail never enters
the Web Push payload.

Subscriptions and pending delivery are durable under
`/data/notifications/`. The VAPID P-256 private key is generated once by
`kaos-h3 setup`, mounted only into Governor Worker and Governor Tools, and is
never exposed through the API. The PWA receives only its derived public key.
Push endpoints are restricted server-side to known Apple, Google, and Mozilla
Web Push services.

Web Push does not replace the durable inbox. Failed or delayed push delivery
does not lose the record, and the on-demand Shortcut can always read the current
pending state directly.

### AI Task completion

When a personal AI Task reaches `previewed` or `failed`, Governor enqueues an
ephemeral Web Push that opens `/#/ai-tasks`. The lock-screen messages are fixed
to `AI Task is ready.` and `AI Task needs attention.`; prompts, results, source
titles, medical content, record ids, and user identity never enter the payload.
The API process receives write access only to the shared subscription/outbox
files and does not receive the VAPID private key; Governor Worker remains the
only sender.

These events do not create a Notification Inbox record, require an ACK, or use
Pushover. The personal AI Task archive is the durable source of truth. Family
AI Tasks have a separate archive and do not send Web Push until that profile has
an explicit device-enrollment design. AI Task execution, archive deletion, and
completion signaling belong to Governor, not n8n.

### Optional ChatGPT Access

Do not put the Shortcut or Governor bearer token in a ChatGPT prompt or URL. If
conversational inbox access is added later, expose it through a narrow read-only
OAuth-protected MCP server. Do not use scheduled ChatGPT polling as the routine
notification transport.

## Cutover

1. Keep the verified Governor inbox, PWA acknowledgement, and on-demand
   Shortcut read operational.
2. Enable Web Push on the installed personal PWA and run `Send test`.
3. Observe Web Push and Pushover in parallel for seven days after the test.
4. Disable Pushover without deleting its secrets or prior outbox state.
5. After a rollback window, remove the Pushover transport and credentials.

This workflow belongs to Governor and its clients. n8n may monitor scheduled
workflow health, but it does not own notification records, delivery, or
acknowledgements.

Reference: [Web Push for Web Apps on iOS and iPadOS](https://webkit.org/blog/13878/web-push-for-web-apps-on-ios-and-ipados/).
