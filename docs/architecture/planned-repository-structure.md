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
│   │       └── imap/
│   └── family-ai-gateway/
├── integrations/
│   ├── openclaw/
│   │   ├── skills/
│   │   ├── mcp/
│   │   └── config-templates/
│   └── discoord/
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
- KaosAI/OpenClaw planner integration behind KaosBrain Guard
- Family AI gateway code
- Discord adapters and interaction contracts
- the office Fax Connector
- schemas and deployment definitions
- migration and operations documentation

### `zinsss/KaosGDD` continues to own

- Family KaosGDD web UI
- family browser presentation, embedded AI chat, and PWA behavior

The main KaosGDD web repository is retained only as reference. It is not part
of the target deployment. A future personal UI should begin only after a
specific unmet workflow justifies it. A narrow `kaosgdd.net` settings/admin
page remains in scope for KaosGDD configuration.

The old `kaosgdd-portal` personal/main route is deprecated during migration.
`family.kaosgdd.net` is the only retained full custom KaosGDD portal, while
`kaosgdd.net` remains settings/admin only. If the old
`kaosgdd-brain` service still has deterministic API duties during host
migration, rename it to transitional `kaosgovernor-legacy-api` and continue absorbing its
modules into KaosGovernor.

The target architecture does not require a custom personal Memos frontend.
Personal Memos workflows use the upstream Memos PWA, scoped iOS clients, and
the retained Discord `#brain` conversation when AI is useful. Direct Discord
Memos channels retire under the brain-only decision. The family frontend may
retain its simplified Memos experience because Family KaosGDD remains a
supported product.

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
- KaosAI/OpenClaw configuration committed here must contain placeholders,
  scoped planner policies, and no provider credentials.
- Model weights are managed as deployment artifacts, never Git objects.
- Compose files must pin production image versions or digests.
- Production data paths are documented but never created or populated by repository bootstrap scripts.
