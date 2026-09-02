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
│   ├── family-ai-gateway/
│   └── family-portal/       shared personal/family KaosGDD PWA source
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
- KaosBrain-OpenAI/OpenClaw planner integration behind KaosBrain Guard
- Family AI gateway code
- the shared personal/family KaosGDD PWA source currently deployed from
  `apps/family-portal`
- Discord adapters and interaction contracts
- the office Fax Connector
- schemas and deployment definitions
- migration and operations documentation

The current canonical deployed static source is `apps/family-portal`, which
already selects personal or family presentation by hostname. Preserve the
personal colors and route variations at `kaosgdd.net`, while retaining strict
server-side personal/family authorization. The earlier standalone KaosGDD web
repository remains migration and design reference until its retained history
and ownership are explicitly reconciled; do not maintain two divergent live
copies.

If the old
`kaosgdd-brain` service still has deterministic API duties during host
migration, rename it to transitional `kaosgovernor-legacy-api` and continue absorbing its
modules into KaosGovernor.

The personal PWA may provide recent/search/create Memos workflows and exact
links while upstream Memos remains authoritative and available for advanced
editing. Direct Discord Memos channels retire under the brain-only decision.
The family frontend retains its simplified family-scoped Memos experience.

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
- KaosBrain-OpenAI/OpenClaw configuration committed here must contain
  placeholders, scoped planner policies, and no provider credentials.
- Model weights are managed as deployment artifacts, never Git objects.
- Compose files must pin production image versions or digests.
- Production data paths are documented but never created or populated by repository bootstrap scripts.
