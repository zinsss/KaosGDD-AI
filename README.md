# KaosGDD-AI

Architecture, deterministic orchestration, AI integrations, and deployment plans for the next KaosGDD platform.

> Status (2026-08-28): H3 Governor/backends and H4 KaosBrain are in production.
> The office Fax Connector and Fax Bridge are active beside HylaFAX. Migration
> remains incremental: clinic services and stateful data are never moved or
> replaced automatically.

## System Roles

- **KaosAI**: optional model/planner implementation used by KaosBrain, currently an OpenClaw/hosted-or-local model slot when explicitly enabled.
- **KaosBrain**: interpretation and reasoning layer on H4. It handles natural language and proposes guarded structured actions, but does not directly mutate authoritative services.
- **KaosGovernor**: deterministic authority on the H3+ backend. It validates operations, owns domain workflows, records audit history, and calls backend services.
- **KaosDiscoord**: replaceable Discord transport for messages, attachments, IDs, controls, and response formatting. Its canonical package is `integrations/discoord`; the historical H3 service name remains temporarily for rollback compatibility.
- **Family AI**: a separately scoped assistant served by H4 or a future optional worker.
- **Authoritative backends**: Radicale, Memos, Paperless, HylaFAX, and other service-owned data stores.
- **Family KaosGDD**: the retained family web interface and embedded family AI chat. The frontend remains in the `zinsss/KaosGDD` repository.
- **Personal clients**: Discord for orchestration and native iOS Calendar/Reminders for calendar, tasks, and supplies. No main KaosGDD web UI is planned; it may be designed later only if a concrete need appears.

KaosBrain and Family AI never become sources of truth. They call narrow KaosGovernor tools. KaosGovernor applies deterministic validation before changing an authoritative backend. Deterministic clients may call Governor without invoking Brain.

## Target Hardware

| Host | Planned responsibility |
| --- | --- |
| Office H3+ | KaosPACS, KaosPACS-AIO, Paperless, Stirling-PDF, RustDesk, HylaFAX, Tailscale |
| H3+ 32 GB backend | KaosGovernor, Governor PostgreSQL, Radicale, Memos, Family KaosGDD, and service edge |
| H4 Ultra | KaosBrain, optional KaosAI runtime, and separately scoped personal/family AI sessions |
| Turing Pi 2 / RK1 | Optional future worker pool; never required for normal operation |

## H3+ Quick Start

```bash
git clone git@github.com:zinsss/KaosGDD-AI.git /srv/projects/KaosGDD-AI
cd /srv/projects/KaosGDD-AI
./deploy/h3-backend/kaos-h3 setup
```

Fill the generated `.env` and Discord token file, then run:

```bash
./deploy/h3-backend/kaos-h3 test
./deploy/h3-backend/kaos-h3 up
```

See [the H3+ deployment guide](deploy/h3-backend/README.md). Memos and
Radicale have a separate guarded migration and are never started empty by the
normal `up` command.

## Repository Scope

This repository will contain Kaos-owned orchestration code and deployment definitions:

- KaosGovernor and its domain modules
- KaosAI/OpenClaw integration and guarded planner contracts
- Family AI gateway
- Discord adapters
- office Fax Connector
- API, MCP, event, and job contracts
- Docker Compose definitions for the planned hosts
- migration, security, and operations documentation
- Korean command and tool-use evaluation cases

It will not contain:

- forks of OpenClaw, Radicale, Memos, Paperless, or Stirling-PDF
- model weights
- production databases or uploaded files
- credentials, bot tokens, VAPID private keys, or Cloudflare secrets
- PACS or DICOM data

Upstream applications will be referenced using pinned release versions or image digests.

## Documents

- [Target architecture](docs/architecture/target-architecture.md)
- [Detailed H4/H3 production plan](docs/architecture/h4-h3-production-plan.md)
- [Planned repository structure](docs/architecture/planned-repository-structure.md)
- [Security and trust boundaries](docs/architecture/security-boundaries.md)
- [Current Brain conversion inventory](docs/migration/current-brain-inventory.md)
- [Migration strategies and phased plan](docs/migration/migration-plan.md)
- [Brain / Governor / Discoord / iOS implementation tracker](docs/migration/brain-governor-discoord-ios-plan.md)
- [KaosGovernor Discord bot rollout](docs/operations/discord-governor-bot.md)
- [Naver mail migration](docs/operations/naver-mail.md)
- [Governor Memos search](docs/operations/memos-search.md)
- [Current production and recovery map](docs/operations/production-recovery.md)
- [Office Fax Connector and Bridge](deploy/office-fax-connector/README.md)
- [H3+ backend deployment](deploy/h3-backend/README.md)
- [H3+ stateful migration](docs/migration/h3-backend-cutover.md)

## Non-Negotiable Principles

1. No all-at-once migration.
2. Office PACS, DICOM, fax, and Paperless remain stable during this project.
3. AI has no direct database, Docker, SSH, or unrestricted shell access.
4. KaosGovernor owns validation, authorization, confirmations, and audit.
5. Native services remain useful without KaosBrain.
6. Every cutover has a tested rollback path.
7. Stateful migrations require backups, checksums, and a final write freeze.
