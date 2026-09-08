# n8n workflow migration plan

> Status: n8n infrastructure preparation only. No live KaosGDD workflow has
> moved to n8n, and no duplicate scheduler or poller should be enabled yet.

## Role and boundary

n8n keeps its upstream product name and native interface. In KaosGDD it is an
optional workflow backend for external integrations, schedules, retries, and
human-review steps. It is not a replacement for KaosGovernor or KaosBrain.

```text
KaosGDD PWA
    |
KaosGovernor ---- native domain services
    |              (Paperless, Radicale, Memos, mail/fax state)
    |
    +---- n8n ---- external services and multi-step automation
    |
    +---- KaosBrain/OpenAI ---- classification, synthesis, reasoning
```

KaosGovernor remains the authority for identity, validation, confirmations,
audit records, and the final state visible in the PWA. n8n owns only its
workflow definitions, encrypted credentials, and execution history. An n8n
execution is not a KaosGDD domain record.

## Current workflow assessment

| Workflow | Initial decision | Reason and possible n8n role |
| --- | --- | --- |
| Google Gmail/Calendar/Drive integration | Build first in n8n | New OAuth-heavy integration with mature n8n nodes; no live KaosGDD workflow to disrupt. |
| Consensus academic search | Good pilot | n8n can call the official API or MCP, normalize citations, and return bounded source records to Governor. |
| General third-party API jobs | Good candidate | HTTP credentials, schedules, retry/backoff, branching, and webhook handling fit n8n. |
| n8n AI Assistant through OpenClaw | Possible later experiment | OpenClaw can expose an OpenAI-compatible endpoint backed by its OpenAI OAuth profile, but the main Gateway bearer token is an operator credential and must not be stored in n8n. |
| Naver IMAP polling and target-folder archive | Shadow-test later | n8n can poll IMAP, but Governor already has working mailbox state, Pushover attention, detail fetch, and batch actions. Avoid two active pollers. |
| Unread mail mark-read/delete batches | Keep in Governor | User-confirmed destructive actions and mailbox-generation checks belong at the governed API boundary. n8n may execute a future approved job, but must not decide the action. |
| Pushover delivery | Keep current worker initially | The durable outbox and deduplication already work. A shadow n8n delivery can be compared later without sending notifications. |
| Daily digest | Keep current worker initially | Disabled Discord delivery and current state semantics must remain stable; n8n could assemble external content later. |
| AI Tasks official allowlist search | Keep in Governor | Domain allowlists, SSRF checks, source provenance, textbook separation, and HIRA-specific handling are safety-critical code. |
| AI Tasks provider calls | Candidate adapter | n8n may gather Consensus or other external evidence; KaosBrain/OpenAI remains responsible for synthesis and Governor archives the result. |
| Paperless upload and metadata apply | Keep in Governor | Paperless ownership, existing-tag validation, preview/confirmation, and inbox/archive state are domain operations. |
| Radicale calendar and tasks | Keep native | Radicale is the source of truth and the calendar adapter owns KaosGDD semantics. n8n may import external calendars through a governed job. |
| Recurring task creation | Keep current worker | It already has KST scheduling and durable same-day idempotency. A second scheduler would risk duplicates. |
| Fax archive, acknowledgement, and sending | Keep in Governor/connector | Fax transport, file validation, failure acknowledgement, and auditability should not be rebuilt visually. |
| System updates, reboot, shell scripts | Do not migrate | n8n has powerful command nodes; exposing them would weaken the separate system-operator boundary. |

## Migration contract

Every migrated workflow should use the same contract:

1. Governor creates a stable job ID with a versioned, size-limited payload.
2. Governor calls an internal n8n webhook using a dedicated narrow credential,
   never the general Governor or system-operator token.
3. n8n validates the job version, performs only its approved external calls,
   and returns normalized results with source URLs and provider timestamps.
4. Governor validates the response, records the audit outcome, and decides
   whether any PWA-visible state may change.
5. User confirmation remains in the PWA/Governor for writes, deletions,
   messages, calendar changes, and other consequential actions.

Webhook endpoints stay on the Docker network or an authenticated tailnet
route. Do not expose test webhooks or the editor directly to the Internet.

## Staged rollout

### Stage 0: infrastructure preparation

- Run n8n and its separate PostgreSQL database on H3.
- Keep the editor loopback-only and create its owner through an SSH tunnel.
- Verify restart persistence and take a paired database, state, and encryption
  key backup.
- Install no community nodes and add no KaosGDD credentials.

Exit gate: health is stable across one controlled restart, backup paths are
included in the H3 backup inventory, and the editor is not publicly reachable.

### Stage 1: non-destructive pilot

- Build one manual Consensus or harmless public-API workflow.
- Accept a synthetic job from Governor and return normalized JSON.
- Store no patient identifiers, document bodies, mail bodies, or credentials
  in pinned execution data.
- Export the reviewed workflow JSON into the repository after removing
  instance-specific IDs and verifying that it contains no credentials.

Exit gate: repeated calls are deterministic enough for the contract, errors
are explicit, and disabling the workflow immediately restores the native path.

### Stage 2: Google integration

- Connect the two Google accounts as distinct n8n credentials.
- Begin read-only: list labels/calendars and fetch bounded metadata.
- Add write actions only behind Governor confirmation and account selection.
- Keep account IDs in configuration; never infer which account receives a
  write from free text alone.

Exit gate: read-only results identify the source account, refresh tokens
survive restart, and every write preview names the exact account and target.

### Stage 3: shadow existing automation

- Select one existing workflow, preferably Naver target-folder polling or a
  non-delivering Pushover projection.
- Run n8n in shadow mode with all writes and notifications disabled.
- Compare item IDs, timestamps, errors, and deduplication with the current
  worker for at least seven days.
- Do not shadow unread-mail deletion, fax sending, or recurring task creation.

Exit gate: no missing/duplicate records, bounded execution data, and a written
cutover/rollback decision.

### Stage 4: one-owner cutover

- Add an explicit owner flag such as `native` or `n8n` to the workflow's
  existing configuration.
- Stop the native owner before activating the n8n owner.
- Keep the native code and state readable for one observation cycle.
- Roll back by disabling the n8n workflow and restoring the native owner; do
  not reverse-migrate n8n execution history into domain state.

## Operational rules

- Pin n8n and PostgreSQL images. Review n8n release notes before upgrades.
- Export workflow JSON after each approved change; credentials remain only in
  n8n's encrypted database.
- Back up `/srv/kaos/data/n8n`, `/srv/kaos/data/n8n-postgres`, and
  `/srv/kaos/secrets/n8n.env` as one recovery set.
- Keep execution pruning enabled. Medical, mail, and document content should
  not remain in execution history longer than required for debugging.
- Never mount `/var/run/docker.sock`, the repository, home directories, or
  broad `/srv` paths into n8n.
- Do not enable Execute Command, arbitrary filesystem access, or unreviewed
  community nodes for production workflows.
- Run n8n's security audit after owner setup and after adding a new workflow.

## Possible later experiment: OpenClaw model bridge

n8n's optional AI Assistant may be tested against an OpenAI-compatible HTTP
endpoint exposed by OpenClaw. In that arrangement n8n authenticates to the
private OpenClaw endpoint, and OpenClaw uses its own OpenAI OAuth profile
internally. n8n does not receive or store the OpenAI OAuth credential.

Do not connect n8n directly to the existing KaosBrain Gateway with its shared
Gateway token. OpenClaw treats that token as owner/operator authority, and AI
Assistant prompts can include workflow definitions and execution data. Before
testing, provide one of these isolation boundaries:

- a separate n8n-only OpenClaw Gateway with a separate token, restricted agent,
  and no shell, system-operation, messaging, filesystem, or destructive tools;
- or a narrow private relay that accepts a dedicated n8n credential, fixes the
  target to the restricted agent/model, enforces payload and rate limits, and
  forwards only the required compatible model calls.

Keep the route on a private H3-to-H4 network. Start with synthetic, non-medical
content and verify `/v1/models` plus a non-streaming chat completion before
entering the endpoint in n8n. The expected model target is
`openclaw/default`, not a raw OpenAI model ID. Do not allow patient data,
mail bodies, document bodies, or production execution data until the isolation,
logging, retention, timeout, and failure behavior have been reviewed.

This is an optional editor-assistance experiment, not a dependency of n8n
workflows. If compatibility or security is unsatisfactory, disconnect the
model and continue running model-free workflows; no KaosGDD workflow ownership
should change as part of this test.

## Recommended first implementation

Use Consensus as the first end-to-end pilot because it is read-only, has a
documented API/MCP surface, returns source metadata, and cannot alter current
KaosGDD state. After that succeeds, connect the two Google accounts in
read-only mode. Existing mail, fax, document, calendar, task, notification,
and system-operation workflows remain native until separately approved.
