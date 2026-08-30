# Security and Trust Boundaries

## Authority Order

```text
User intent
  -> KaosBrain or Family AI interpretation
  -> KaosGovernor authorization and validation
  -> domain module decision
  -> backend adapter
  -> authoritative service
```

The model may propose an operation. It may not authorize itself or bypass Governor validation.

## KaosBrain on H4

Allowed:

- local model inference
- Discord channel handling through the KaosBrain adapter
- approved narrow KaosGovernor tool APIs
- short-lived conversational context

Denied:

- production SSH credentials
- Docker socket
- unrestricted shell or elevated agent tools
- direct PostgreSQL access
- direct Radicale, Memos, Paperless, or HylaFAX credentials
- production filesystem mounts

Discord guild, channel, and user access must be allowlisted. If KaosAI/OpenClaw
is enabled, it remains behind KaosBrain Guard and must not receive Governor
credentials or direct backend credentials.

## Family AI session on H4

- receives a family-scoped Governor credential
- can use only family calendar, family tasks, Rouny, family Memos, and approved weather/read tools
- cannot access personal, clinic, PACS, mail, fax, infrastructure, or administrative tools
- stores only disposable conversation state
- never exposes its Governor credential to browser JavaScript

## KaosGovernor on H3+

- is not publicly exposed
- accepts connections only from the web edge, H4 KaosBrain, Family AI, and allowlisted office connectors
- owns service credentials
- validates schemas, actor scopes, object versions, rate limits, and idempotency
- records all meaningful writes and confirmations

## Confirmation Classes

| Class | Examples | Behavior |
| --- | --- | --- |
| Read | Search calendar, memo, or documents | No confirmation |
| Reversible explicit write | Create one clearly specified task | Execute with receipt and optional Undo |
| Ambiguous write | Multiple matching classes or unclear year | Clarify before planning |
| Destructive or bulk | Delete, bulk edit, overwrite metadata | Exact diff plus expiring one-time confirmation |
| External transmission | Send fax or externally visible message | Exact destination/file confirmation |
| Infrastructure/security | Restart critical service, secrets, backups | Outside AI path or separately hardened control flow |

Confirmations are bound to the normalized operation hash, actor, expiry, and current object version. A generic model-interpreted `yes` is insufficient.

## Governed System Operations

Brain may eventually query health, explain failures, and propose typed system
operations. It does not become a privileged runner. Governor validates the
actor, exact target, requested version, preconditions, confirmation, and audit
record. A restricted executor beside each managed host runs only a versioned
allowlisted runbook.

The model never receives SSH keys, sudo access, a Docker socket, service
secrets, raw package-manager arguments, or arbitrary command execution.
PACS/database/OS upgrades require a separately hardened maintenance flow with
verified backup, explicit downtime, and rollback details. See [Brain as Kaos
Gateway and System Operator](brain-system-operations.md).

## Untrusted Content

Mail, memos, PDFs, OCR text, web pages, and fax content are data, not instructions. Retrieved content must never be allowed to expand tool permissions or alter system policy.
