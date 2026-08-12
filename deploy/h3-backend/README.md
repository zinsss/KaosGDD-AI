# H3+ Kaos backend deployment

This is the supported fresh-install target for the 32 GB H3+ backend. A clone
can build and start Governor without copying production data into Git or
changing the Office Kaos host.

## Host prerequisites

- x86-64 Debian 13 or Ubuntu 24.04 LTS
- Docker Engine with Compose v2
- Git, curl, OpenSSL, rsync, and sqlite3
- Tailscale joined to the Kaos tailnet
- synchronized system time and a static LAN reservation
- the deployment user allowed to run Docker

Use a distinct hostname such as `kaos-core`. Do not reuse `kaos`,
`kaos-legacy`, or a PACS hostname.

## First installation

```bash
sudo install -d -m 0755 -o "$USER" -g "$(id -gn)" /srv/projects
git clone git@github.com:zinsss/KaosGDD-AI.git /srv/projects/KaosGDD-AI
cd /srv/projects/KaosGDD-AI
./deploy/h3-backend/kaos-h3 setup
```

Then edit:

```text
deploy/h3-backend/.env
deploy/h3-backend/secrets/discord_bot_token
```

The setup command generates `governor_api_token`. Add
`memos_access_token` only when Memos search is enabled, and
`naver_mail_password` only when Naver mail is enabled.

Run:

```bash
./deploy/h3-backend/kaos-h3 test
./deploy/h3-backend/kaos-h3 up
```

`up` runs preflight, builds locally, starts Governor, and waits for its health
endpoint. It does not start Memos or Radicale and cannot touch PACS, DICOM,
Paperless, HylaFAX, or RustDesk.

## Network binding

The default API binding is loopback only:

```text
GOVERNOR_BIND_ADDRESS=127.0.0.1
```

When KaosBrain moves to H4, bind Governor to the H3+ Tailscale address and
allow TCP 8097 only from H4 in the host firewall. Do not publish Governor
through Caddy, cloudflared, or the public Internet.

Memos and Radicale default to loopback. Their native clients require a
separate, intentional Caddy/Tailscale or CalDAV routing design.

## Commands

```text
kaos-h3 setup
kaos-h3 preflight
kaos-h3 test
kaos-h3 build
kaos-h3 up
kaos-h3 restart
kaos-h3 status
kaos-h3 logs
kaos-h3 down
kaos-h3 backends-preflight
kaos-h3 backends-up
kaos-h3 backends-down
```

`down` and `backends-down` never delete volumes or host data.

## Stateful backends

`compose.backends.yaml` pins the exact Memos and Radicale images observed on
the current server. It is deliberately excluded from normal `up`.

`backends-up` refuses to start unless it finds:

- a cleanly copied `memos_prod.db` that passes SQLite integrity checking
- Radicale `config` and `users`
- a Radicale collections directory

Follow [the H3 backend migration runbook](../../docs/migration/h3-backend-cutover.md)
before using this command. Starting empty services and importing data later is
not an approved production migration path.

## Rollback

Governor rollback is simply:

```bash
./deploy/h3-backend/kaos-h3 down
```

The existing production Brain/Governor continues until its domain is cut over.
For Memos and Radicale, keep the old containers stopped and old data untouched
during the observation period so routing can be restored without reverse
migration.
