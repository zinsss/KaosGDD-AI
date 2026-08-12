# Planned Repository Structure

This is a target structure, not an instruction to create every directory immediately. Directories should be introduced only when their first real implementation or contract is added.

```text
KaosGDD-AI/
├── apps/
│   ├── governor/
│   │   ├── api/
│   │   ├── core/
│   │   ├── scheduler/
│   │   ├── calendar/
│   │   ├── memos/
│   │   ├── mail/
│   │   ├── fax/
│   │   ├── inbox/
│   │   ├── notifications/
│   │   ├── audit/
│   │   └── adapters/
│   │       ├── radicale/
│   │       ├── memos/
│   │       ├── paperless/
│   │       ├── stirling/
│   │       ├── imap/
│   │       └── discord/
│   └── family-ai-gateway/
├── integrations/
│   ├── openclaw/
│   │   ├── skills/
│   │   ├── mcp/
│   │   └── config-templates/
│   └── discord/
├── connectors/
│   └── fax/
├── contracts/
│   ├── governor-openapi/
│   ├── governor-mcp/
│   ├── jobs/
│   └── events/
├── deploy/
│   ├── h4-kaosbrain/
│   ├── h3-backend/
│   ├── optional-rk1-workers/
│   └── office-connectors/
├── docs/
│   ├── architecture/
│   ├── decisions/
│   ├── migration/
│   ├── operations/
│   └── security/
└── tests/
    ├── contracts/
    ├── integration/
    └── language-evals/
```

## Repository Boundaries

### This repository owns

- deterministic Governor code
- Kaos-specific OpenClaw integration
- Family AI gateway code
- Discord adapters and interaction contracts
- the office Fax Connector
- schemas and deployment definitions
- migration and operations documentation

### `zinsss/KaosGDD` continues to own

- main KaosGDD web UI
- Family KaosGDD web UI
- custom personal/family Memos frontend
- browser-specific presentation and PWA behavior

### Upstream projects continue to own

- OpenClaw runtime
- Radicale
- Memos
- Paperless-ngx
- Stirling-PDF
- HylaFAX

No upstream source should be copied here merely to make deployment convenient. Compose definitions pin and configure upstream images.

## Configuration Rules

- Commit `.env.example` files only.
- Production secrets remain outside Git and are mounted through host-managed secret files.
- OpenClaw configuration committed here must contain placeholders, scoped tool policies, and no provider credentials.
- Model weights are managed as deployment artifacts, never Git objects.
- Compose files must pin production image versions or digests.
- Production data paths are documented but never created or populated by repository bootstrap scripts.
