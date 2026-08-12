# KaosGovernor Discord bot rollout

KaosGovernor uses its own deterministic bot for notifications, inbox/fax/mail
workflows, confirmation buttons, timed jobs, and system operations. KaosBrain
uses OpenClaw's separate Discord integration. Family chat remains in its PWA.

The bot has no Governor API connection yet. It temporarily hosts the tested
KaosMail worker in-process as part of the planned Governor modular monolith.

## Discord application

1. Create a private Discord application named `KaosGovernor` and add its bot.
2. Do not enable Message Content intent.
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

It may run temporarily on the current Kaos host. Move the same image and `.env`
to RK1-1 when ready.

## Next boundary

The next step connects this transport to a narrow authenticated Governor API.
Discord callbacks submit typed commands and confirmation tokens; they never call
Radicale, Memos, Paperless, HylaFAX, Docker, or databases directly.
