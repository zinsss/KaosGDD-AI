# KaosGDD-AI

Architecture, deterministic orchestration, AI integrations, and deployment plans for the next KaosGDD platform.

> Status: preparation only. This repository does not yet replace the production KaosGDD Brain or deploy services to the H4/Turing Pi infrastructure.

## System Roles

- **KaosBrain**: OpenClaw and the main local model on the H4 Ultra. It interprets language, reasons, and selects tools.
- **KaosGovernor**: deterministic authority on RK1-1. It validates operations, owns domain workflows, records audit history, and calls backend services.
- **Family AI**: independent constrained 4B family assistant on RK1-2.
- **Authoritative backends**: Radicale, Memos, Paperless, HylaFAX, and other service-owned data stores.
- **KaosGDD**: main and family web interfaces. The existing frontend remains in the `zinsss/KaosGDD` repository.

KaosBrain and Family AI never become sources of truth. They call narrow KaosGovernor tools. KaosGovernor applies deterministic validation before changing an authoritative backend.

## Target Hardware

| Host | Planned responsibility |
| --- | --- |
| Office H3+ | KaosPACS, KaosPACS-AIO, Paperless, Stirling-PDF, RustDesk, HylaFAX, Tailscale |
| H4 Ultra | KaosBrain: OpenClaw and main local model |
| RK1-1 | KaosGovernor processes and Governor PostgreSQL |
| RK1-2 | Independent Family AI, family chat gateway, Web Push |
| RK1-3 | Radicale and Memos with persistent storage |
| RK1-4 | Main/family KaosGDD web UIs, custom Memos UI, Caddy, cloudflared |

## Repository Scope

This repository will contain Kaos-owned orchestration code and deployment definitions:

- KaosGovernor and its domain modules
- OpenClaw Kaos integration and MCP registration
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
- [Planned repository structure](docs/architecture/planned-repository-structure.md)
- [Security and trust boundaries](docs/architecture/security-boundaries.md)
- [Current Brain conversion inventory](docs/migration/current-brain-inventory.md)
- [Migration strategies and phased plan](docs/migration/migration-plan.md)
- [KaosGovernor Discord bot rollout](docs/operations/discord-governor-bot.md)
- [Naver mail migration](docs/operations/naver-mail.md)

## Non-Negotiable Principles

1. No all-at-once migration.
2. Office PACS, DICOM, fax, and Paperless remain stable during this project.
3. AI has no direct database, Docker, SSH, or unrestricted shell access.
4. KaosGovernor owns validation, authorization, confirmations, and audit.
5. Native services remain useful without KaosBrain.
6. Every cutover has a tested rollback path.
7. Stateful migrations require backups, checksums, and a final write freeze.
