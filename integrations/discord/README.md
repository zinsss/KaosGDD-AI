# KaosGovernor Discord transport

This deterministic bot is separate from the KaosBrain/OpenClaw Discord
integration. It contains no AI or domain decisions.

The preparation build exposes `/status`, `/confirmation-test`, `/fax-send`,
`/mail-organizer-now`, `/mail-organizer-schedule`, `/health`, and `/ready`.
Every interaction must match configured server, channel, and user
allowlists. It requests Message Content intent only when the optional
Telegram-compatible fax upload/reply flow is enabled. It has no public HTTP
route.

Bot-authored messages use a shared Discord Markdown renderer for headings,
fields, lists, quotes, and compact footers. Dynamic values are escaped, mentions
are disabled, and oversized messages fail explicitly instead of being silently
truncated. Domain adapters should use this renderer rather than assembling
untrusted Markdown directly.

Version `0.4.0` hosts the first deterministic Governor modules: read-only
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

See [the deployment runbook](../../docs/operations/discord-governor-bot.md).
