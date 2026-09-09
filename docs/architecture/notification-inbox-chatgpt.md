# Governor Notification Inbox and ChatGPT Delivery

Decision date: 2026-09-09

Status: Governor inbox, personal PWA, and read-only on-demand Shortcut API
implemented; PWA Web Push is the target alert transport.

## Decision

All KaosGDD operational notifications have one durable source of truth in
KaosGovernor. The personal PWA and iOS Shortcuts are clients of that inbox;
neither owns notification state.

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

Governor will send an event-driven Web Push when a new inbox record is created.
The notification opens `https://kaosgdd.net/#/notifications`; review and
acknowledgement remain in the protected PWA. Lock-screen payloads should be
minimal so mail, fax, and medical details are not exposed before the PWA opens.

Web Push does not replace the durable inbox. Failed or delayed push delivery
does not lose the record, and the on-demand Shortcut can always read the current
pending state directly.

### Optional ChatGPT Access

Do not put the Shortcut or Governor bearer token in a ChatGPT prompt or URL. If
conversational inbox access is added later, expose it through a narrow read-only
OAuth-protected MCP server. Do not use scheduled ChatGPT polling as the routine
notification transport.

## Cutover

1. Keep the verified Governor inbox, PWA acknowledgement, and on-demand
   Shortcut read operational.
2. Implement PWA Web Push and run a synthetic low-priority test.
3. Observe Web Push and Pushover in parallel for seven days.
4. Disable Pushover without deleting its secrets or prior outbox state.
5. After a rollback window, remove the Pushover transport and credentials.

This workflow belongs to Governor and its clients. n8n may monitor scheduled
workflow health, but it does not own notification records, delivery, or
acknowledgements.

Reference: [Web Push for Web Apps on iOS and iPadOS](https://webkit.org/blog/13878/web-push-for-web-apps-on-ios-and-ipados/).
