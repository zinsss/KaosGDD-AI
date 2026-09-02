# Current Production and Recovery Map

This document is the concise recovery source for the active KaosGDD deployment
as of 2026-08-28. It describes ownership and reconstruction; it never contains
secret values.

## H3: deterministic application plane

Checkout:

```text
/srv/projects/KaosGDD-AI
```

Canonical state:

```text
/srv/kaosgdd/kaosgovernor
```

Service-native data and configuration:

```text
/srv/kaos/data
/srv/kaos/config
/srv/kaos/secrets
```

Active services include Governor Discord/tools, Governor API and PostgreSQL,
Radicale, Memos, Vaultwarden, SFTPGo, Calendar Adapter, Family portal, Caddy,
and cloudflared. The Calendar Adapter mounts repository source directly from
`apps/calendar-adapter`; `/srv/kaos/data/calendar-adapter` is a retained legacy
copy and is not the live application mount.

Read-only recovery checks:

```bash
git -C /srv/projects/KaosGDD-AI status --short --branch
docker ps
curl -fsS http://100.78.124.43:8097/health
curl -fsS http://100.78.124.43:8097/ready
```

Normal deployment entry points:

```bash
./deploy/h3-backend/kaos-h3 test
./deploy/h3-backend/kaos-h3 up
./deploy/h3-backend/kaos-h3 family-up
./deploy/h3-backend/kaos-h3 services-up
./deploy/h3-backend/kaos-h3 edge-up
```

Stateful service recovery must use the guarded backup, checksum, write-freeze,
and rollback process in [`h3-backend-cutover.md`](../migration/h3-backend-cutover.md).

## H4: language and AI plane

Checkout:

```text
/srv/projects/KaosGDD-AI
```

Canonical runtime paths:

```text
/srv/kaosgdd/kaosbrain
/srv/kaosgdd/kaosai
/srv/kaosgdd/secrets
```

The active system service reads `/srv/kaosgdd/kaosbrain/kaosbrain.env`. A file
under `/srv/kaos/brain` is a legacy copy and is not authoritative.

Current production mode:

- KaosBrain Discord adapter and deterministic Guard enabled
- local Ollama chat and deep fallback models available
- Governor tools enabled over Tailscale
- KaosBrain-OpenAI/OpenClaw enabled in guarded chat mode
- OpenClaw model `openai/gpt-5.6-sol`
- imaging second-look forwarding enabled
- loopback-only OpenClaw reauthentication agent enabled

Recovery checks:

```bash
systemctl status kaosbrain.service --no-pager
systemctl --user status kaosai-openclaw-reauth-agent.service --no-pager
docker ps --filter name=kaos-brain
curl -fsS http://100.113.169.46:8099/health
ollama list
```

Rebuild H4 from the repository and file-backed secrets. H4 holds no
authoritative calendar, task, memo, mail, document, fax, PACS, or Governor
database state.

## Office Kaos: clinic and hardware plane

Office Kaos retains PACS/DICOM, Paperless, Stirling-PDF, RustDesk, HylaFAX, the
physical modem, the authenticated Fax Connector, and the local Fax Bridge.

Critical fax paths:

```text
/var/spool/hylafax
/etc/hylafax/config.ttyACM0
/srv/kaos/data/kaosgdd/brain/fax-outgoing
```

The HylaFAX spool must also contain readable generated conversion caches:

```text
/var/spool/hylafax/etc/setup.cache
/var/spool/hylafax/etc/setup.modem
```

Their canonical sources are `/etc/hylafax/setup.cache` and
`/etc/hylafax/setup.modem`. Missing spool copies cause document formatting to
fail before the modem dials. They may be restored from the canonical files
without restarting HylaFAX, followed by the Office fax `preflight` check.

Critical fax services:

```text
hylafax.service
faxq.service
hfaxd.service
faxgetty@ttyACM0.service
kaos-office-fax-connector
kaosgdd-fax-bridge
kaos-hylafax-backup.timer
kaos-faxmail-retention.timer
```

The archived `KaosFaxMail` repository is historical only:

```text
/srv/projects/_archive/KaosFaxMail-archived-20260828
```

It is not a dependency of any running fax service.

Never restore the old mailbox or Telegram fax plan into production. The active
path is Discord → H3 Governor → authenticated Office Fax Connector → shared
queue → Office Fax Bridge → HylaFAX.

## Secrets

Secrets are file-backed and excluded from Git. Recover them from the protected
host backup or rotate them. Never copy secret values into documentation, Git,
shell history, support output, or chat.

Minimum cross-host credentials that may need rotation after loss are:

- Governor Discord bot token
- KaosBrain Discord bot token
- Governor API token shared only with approved H4/office clients
- Office Fax Connector token
- Memos and Paperless scoped access tokens
- Naver app/mail password
- OpenClaw gateway and reauthentication tokens

## Recovery order

1. Restore host networking, time, Docker, and Tailscale.
2. Restore H3 service-native data and Governor state before application start.
3. Start H3 backends, Governor, family services, and edge through guarded
   deployment commands.
4. Restore H4 file-backed secrets and OpenClaw state, then start KaosBrain.
5. Verify narrow H4-to-H3 tool access.
6. On Office Kaos, verify existing HylaFAX and modem state before starting the
   Connector and Bridge. Never regenerate modem configuration from defaults.
7. Perform external-send testing only with an explicitly confirmed destination
   and document.
