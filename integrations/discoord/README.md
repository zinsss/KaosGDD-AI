# KaosDiscoord

KaosDiscoord is the Discord transport adapter for Kaos. It owns Discord
connections, IDs, commands, interactions, attachments, views, and message
formatting. It calls KaosGovernor for deterministic operations and contains no
AI or model-driven domain decisions.

The current H3 deployment still uses the historical
`kaos-governor-discord` Compose service and container names while the adapter is
being extracted. The canonical Python package and executable are now
`kaosdiscoord`; the old Python import and executable remain temporary
compatibility shims. This preserves the deployed state, volumes, credentials,
and rollback path during migration.

The preparation build exposes `/status`, `/confirmation-test`, `/fax-send`,
`/mail-organizer-now`, `/mail-organizer-schedule`, `/health`, and `/ready`.
Every interaction must match configured server, channel, and user
allowlists. It requests Message Content intent only when the optional
Discord fax upload/reply flow is enabled. It has no public HTTP route.

Version `0.6.0` also exposes the first narrow Governor tool API on the same
loopback-bound listener:

- `POST /api/v1/memos/search`
- `GET /api/v1/memos/{id}`

Both routes require `Authorization: Bearer <GOVERNOR_API_TOKEN>`. They query
Memos live with a dedicated personal access token and never persist memo
content. `/health` and `/ready` do not require the tool token.

Bot-authored messages use a shared Discord Markdown renderer for headings,
fields, lists, quotes, and compact footers. Dynamic values are escaped, mentions
are disabled, and oversized messages fail explicitly instead of being silently
truncated. Domain adapters should use this renderer rather than assembling
untrusted Markdown directly.

Version `0.6.0` hosts the first deterministic Governor modules: read-only
Naver IMAP polling with UID checkpointing and Discord Markdown delivery. The mail
logic lives under `apps/governor`; the Discord package only renders and transports
the resulting typed mail and attachment objects. Archive delivery and organizer
controls use separate allowlisted channels. It also provides the scheduled
all-folder unread organizer with one persistent direct-action message per mail
and confirmed Naver deletion.

The fax module writes validated PDF manifests into the existing shared fax
bridge queue; it never submits directly to the modem. It observes bridge and
HylaFAX completion files read-only, mirrors lifecycle notifications, archives
received/sent PDFs, and deletes Discord source messages only after confirmed
transmission. Existing files and jobs are baselined on first start.

Task due notifications remain one-shot by default. When
`DISCORD_TASK_DUE_REPEAT_NOTIFICATIONS_ENABLED=true`, task reminders resend every
30 minutes until the newest reminder message is acknowledged with `OK` or
cancelled with `Stop`; normal notifications are unchanged.

See [the deployment runbook](../../docs/operations/discord-governor-bot.md).
