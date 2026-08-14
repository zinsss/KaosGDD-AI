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

The default health binding is loopback only:

```text
GOVERNOR_BIND_ADDRESS=127.0.0.1
```

KaosBrain should use the separate tool API, not the health port:

```text
GOVERNOR_BRAIN_TOOLS_ENABLED=true
GOVERNOR_BRAIN_TOOLS_BIND_ADDRESS=<H3_TAILSCALE_IP>
GOVERNOR_BRAIN_TOOLS_PORT=8098
```

The tool API requires the `GOVERNOR_API_TOKEN` bearer token and exposes only
narrow `/tools/...` endpoints for Brain. Allow TCP 8098 only from H4 in the
host firewall. Do not publish Governor tools through Caddy, cloudflared, or the
public Internet.

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
kaos-h3 services-preflight
kaos-h3 services-up
kaos-h3 services-down
kaos-h3 family-preflight
kaos-h3 family-up
kaos-h3 family-down
kaos-h3 edge-preflight
kaos-h3 edge-up
kaos-h3 edge-down
```

`down`, `backends-down`, `services-down`, `family-down`, and `edge-down` never
delete volumes or host data.

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

`compose.services.yaml` and `compose.edge.yaml` prepare the broader H3 service
move for Radicale, Memos, Vaultwarden, SFTPGo, Family portal, Caddy, and
cloudflared. Use their preflight commands only after data and secrets are
staged. The transitional `family-*` commands are for temporary legacy family
APIs only; they are not the final KaosGovernor implementation.

See [the H3 service migration prep note](../../docs/migration/h3-service-migration-prep.md).

## Rollback

Governor rollback is simply:

```bash
./deploy/h3-backend/kaos-h3 down
```

The existing production Brain/Governor continues until its domain is cut over.
For Memos and Radicale, keep the old containers stopped and old data untouched
during the observation period so routing can be restored without reverse
migration.
