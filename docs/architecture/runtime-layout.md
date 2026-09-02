# Runtime Layout

KaosGDD is the project name. Runtime paths should keep the project-owned
components easy to see without pulling every ready-made backend into the same
namespace.

## Canonical Project Paths

```text
/srv/kaosgdd/
  kaosbrain/
    KaosBrain AI orchestrator, Discord-facing runtime, guard, and local worker env
  kaosgovernor/
    KaosGovernor API, workers, scheduler, durable operation state
  secrets/
    project-owned runtime secrets mounted into containers as /run/secrets
```

## Names

- KaosGDD: the whole system and project.
- KaosBrain: the top AI manager/orchestrator for KaosGDD. It owns language
  interpretation, provider routing, guarded structured action proposals, and
  narrow Governor tool calls.
- KaosBrain-OpenAI: the OpenClaw/ChatGPT Pro provider implementation formerly
  called KaosAI. It is a Brain dependency, not a source of truth.
- KaosGovernor: the deterministic authority for rules, confirmations,
  idempotency, audit, jobs, and service tool APIs.

Current live OpenClaw/OpenAI paths and environment variables may still use the
legacy `kaosai` name. Do not move live env files, secrets, systemd units, or
service data during a naming cleanup; migrate host paths separately.

## Ready-Made Backends

Ready-made services stay independently named. Do not bury them under
KaosBrain or KaosGovernor:

```text
/srv/kaos/data/radicale
/srv/kaos/data/memos
/srv/kaos/data/vaultwarden
/srv/kaos/data/sftpgo
/srv/kaos/config/radicale
/srv/kaos/config/Caddyfile
```

These services are part of the KaosGDD deployment, but they are not KaosBrain
or KaosGovernor internals.

The H3 backend deploy therefore uses two roots:

- `GOVERNOR_STATE_ROOT=/srv/kaosgdd/kaosgovernor` for Governor-owned mail,
  fax, Discord channel, scheduler, audit, and durable operation state.
- `KAOS_ROOT=/srv/kaos` for ready-made backend service data and config such as
  Radicale, Memos, Vaultwarden, SFTPGo, Caddy, and cloudflared.

## Compatibility

Older live installs may still use:

```text
/srv/kaos/brain
/srv/kaos/secrets
/srv/kaos/data/kaosgdd-ai/governor
```

Deployment scripts may keep these paths working while the host is migrated.
Do not move live env files, secrets, or service data during an unrelated code
change. A host path migration should be a separate operation with:

- service stop
- file copy preserving ownership and modes
- systemd unit reinstall
- health check
- rollback path back to the previous files
