# Runtime Layout

KaosGDD is the project name. Runtime paths should keep the project-owned
components easy to see without pulling every ready-made backend into the same
namespace.

## Canonical Project Paths

```text
/srv/kaosgdd/
  kaosai/
    OpenClaw and hosted/local AI gateway runtime config
  kaosbrain/
    KaosBrain Discord adapter, guard, and local worker env
  kaosgovernor/
    KaosGovernor API, workers, scheduler, durable operation state
  secrets/
    project-owned runtime secrets mounted into containers as /run/secrets
```

## Names

- KaosGDD: the whole system and project.
- KaosAI: the smart planner layer, currently OpenClaw plus hosted or local
  model access.
- KaosBrain: the guarded adapter and messenger layer. It owns Discord context,
  validates KaosAI plans, and calls Governor tools.
- KaosGovernor: the deterministic authority for rules, confirmations,
  idempotency, audit, jobs, and service tool APIs.

OpenClaw is an implementation detail of KaosAI. It should not be named
KaosBrain in paths, service names, or user-facing architecture docs.

## Ready-Made Backends

Ready-made services stay independently named. Do not bury them under
KaosBrain, KaosAI, or KaosGovernor:

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

## Compatibility

Older live installs may still use:

```text
/srv/kaos/brain
/srv/kaos/secrets
```

Deployment scripts may keep these paths working while the host is migrated.
Do not move live env files, secrets, or service data during an unrelated code
change. A host path migration should be a separate operation with:

- service stop
- file copy preserving ownership and modes
- systemd unit reinstall
- health check
- rollback path back to the previous files

