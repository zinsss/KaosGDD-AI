# KaosGovernor Discord bot rollout

KaosGovernor uses its own deterministic bot for notifications, inbox/fax/mail
workflows, confirmation buttons, timed jobs, and system operations. KaosBrain
uses its own guarded Discord adapter. Family chat remains in its PWA.

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
cd /srv/projects/KaosGDD-AI
./deploy/h3-backend/kaos-h3 setup
# Edit deploy/h3-backend/.env and its file-backed secrets.
./deploy/h3-backend/kaos-h3 test
./deploy/h3-backend/kaos-h3 up
```

Never commit `.env`. Port 8097 is loopback-only and must not be routed through
Caddy or cloudflared.

For Memos search, create a dedicated PAT in the personal Memos account and set
the variables documented in [Governor Memos search](memos-search.md). Generate
the Governor API token independently; do not reuse the Memos PAT. The H3 setup
generates this token and mounts it from a file.

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

It may run temporarily on the current Kaos host. The supported destination is
the H3+ backend described in [`deploy/h3-backend`](../../deploy/h3-backend/README.md).

## Boundary

HylaFAX and the physical modem remain permanently on Office Kaos. H3
KaosGovernor must use `FAX_TRANSPORT=connector` with the authenticated Office
Fax Connector; it must not mount or read HylaFAX spool paths directly.

The legacy local fax adapter writes only the narrow, versioned bridge manifest
contract and reads HylaFAX status/archive files. It has no modem, shell, Docker,
or database authority and is valid only when running beside the Office Kaos fax
bridge. The Memos adapter has an account-scoped PAT but exposes only read-only
search and fetch operations. Radicale and Paperless authority are not connected.
On H3, fax stays disabled until the authenticated Office Kaos Fax Connector is
deployed and verified.
