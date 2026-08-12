# KaosGovernor Discord bot rollout

KaosGovernor uses its own deterministic bot for notifications, inbox/fax/mail
workflows, confirmation buttons, timed jobs, and system operations. KaosBrain
uses OpenClaw's separate Discord integration. Family chat remains in its PWA.

The bot temporarily hosts the tested Governor modules in-process as part of the
planned modular monolith. The first narrow tool API provides authenticated,
read-only Memos search and current-content fetch routes.

## Discord application

1. Create a private Discord application named `KaosGovernor` and add its bot.
2. Leave Message Content intent disabled for slash-command-only fax sending.
   Enable it only when `FAX_DISCORD_MESSAGE_INTAKE=true` is needed for the
   `upload PDF`, then `reply fax:<number>` workflow.
3. Install it only in the private Kaos server with `bot` and
   `applications.commands` scopes.
4. Grant View Channels, Send Messages, Embed Links, Attach Files, Read Message
   History, and Use Application Commands only in intended channels.
5. Deny every unrelated channel at the Discord role/channel layer.
6. Enable Developer Mode and copy the server, user, and channel IDs.

Discord permissions and the runtime allowlist are both enforced.

## Deploy

```bash
cd /path/to/KaosGDD-AI/deploy/rk1-1-governor
cp .env.example .env
chmod 600 .env
# Edit .env with the bot token and numeric IDs.
docker compose -f compose.discord.yaml up -d --build
docker compose -f compose.discord.yaml logs -f governor-discord
```

Never commit `.env`. Port 8097 is loopback-only and must not be routed through
Caddy or cloudflared.

For Memos search, create a dedicated PAT in the personal Memos account and set
the variables documented in [Governor Memos search](memos-search.md). Generate
`GOVERNOR_API_TOKEN` independently; do not reuse the Memos PAT.

## Verify

1. `curl http://127.0.0.1:8097/health` reports `status: ok`.
2. `/status` works for an allowed user in an allowed channel.
3. `/confirmation-test` confirms, cancels, and expires without an action.
4. Commands are rejected outside the allowlist.
5. The bot cannot view unrelated Discord channels.
6. `/mail-organizer-now` sends nothing when Naver has no unread mail, or sends a
   paginated digest whose preview/import/read/delete controls work only for an
   allowlisted user.
7. `/mail-organizer-schedule 1 09:00` preserves the current daily KST schedule.
8. `/fax-send 022848302 document.pdf` queues through the existing fax bridge;
   it never calls the modem directly.
9. New received and sent fax PDFs appear once in the configured archive
   channel, while queued/sending/sent/failed notices use the configured
   notification channel.
10. With Message Content intent enabled, a PDF uploaded without text receives
    `Reply directly to this PDF with fax:<number>.` Source upload, command, and
    prompt messages are deleted only after HylaFAX confirms success.
11. An unauthenticated `POST /api/v1/memos/search` returns `401`; the same call
    with `GOVERNOR_API_TOKEN` returns creator-scoped live Memos results.

It may run temporarily on the current Kaos host. Move the same image and `.env`
to RK1-1 when ready.

## Boundary

The temporary fax adapter writes only the narrow, versioned bridge manifest
contract and reads HylaFAX status/archive files; it has no modem, shell, Docker,
or database authority. The Memos adapter has an account-scoped PAT but exposes
only read-only search and fetch operations. Radicale and Paperless authority are
not connected.
