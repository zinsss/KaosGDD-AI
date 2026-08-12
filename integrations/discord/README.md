# KaosGovernor Discord transport

This deterministic bot is separate from the KaosBrain/OpenClaw Discord
integration. It contains no AI or domain decisions.

The preparation build exposes only `/status`, `/confirmation-test`, `/health`,
and `/ready`. Every interaction must match configured server, channel, and user
allowlists. It requests no Message Content intent and has no public HTTP route.

Bot-authored messages use a shared Discord Markdown renderer for headings,
fields, lists, quotes, and compact footers. Dynamic values are escaped, mentions
are disabled, and oversized messages fail explicitly instead of being silently
truncated. Domain adapters should use this renderer rather than assembling
untrusted Markdown directly.

See [the deployment runbook](../../docs/operations/discord-governor-bot.md).
