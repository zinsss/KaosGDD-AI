# KaosGDD Consolidation Inventory

> Snapshot: 2026-09-08. This is a read-only production inventory and a
> consolidation decision record. It does not authorize stopping services,
> deleting containers or data, changing schedule ownership, or pruning Docker.

KaosGDD is not in immediate storage or capacity trouble. The larger risk is
that a growing number of useful features acquires overlapping schedulers,
transports, state, and recovery procedures. Consolidation therefore targets
ownership and operational surface area before it targets container count.

## Decision Rules

1. Each domain operation has one authoritative executor and one authoritative
   state store.
2. n8n may own **when** an ordinary clock-based application workflow starts.
   Governor still owns **what** is allowed and performs KaosGDD domain writes.
3. Continuous queue consumers and short-interval pollers remain native workers
   when they are safer and simpler as long-running processes.
4. Privileged host work remains in systemd or an explicit
   KaosSystemOperator/Codex session. It does not move into n8n, Brain, or the
   PWA.
5. A container or process boundary is retained when it provides useful failure
   isolation. Fewer containers is not by itself a goal.
6. A new ready-made service should either replace an existing custom feature,
   support at least two durable workflows, or provide an upstream capability
   that would be unreasonable to maintain locally.
7. No migration leaves two production schedulers or writers active for the
   same job.
8. Retirements require a dependency check, recovery decision, observation
   period, and explicit approval before destructive cleanup.

## Measured Production Footprint

Measurements below were taken from the live hosts on 2026-09-08.

| Host | Active application footprint | Disk use | Interpretation |
| --- | --- | --- | --- |
| H3 `kaosgdd` | 17 containers | 94 GB / 915 GB (11%) | Main web, domain, scheduling, and personal-service host |
| H4 `kaosbrain` | 1 container, 2 system services, 2 user services | 37 GB / 906 GB (5%) | OpenClaw/OpenAI and transitional Discord/Brain runtime |
| Clinic | 18 containers plus local systemd helpers/timers | 56 GB / 868 GB (7%) | PACS, Paperless, fax, PDF, and remote-access appliance |

The repository checkout is approximately 339 MB. H3 Docker reports about
62 GB of reclaimable build cache and 6.7 GB of reclaimable image data. That is
the largest obvious space recovery, but disk use is low and pruning is a
separate, reversible-maintenance decision. Bind-mounted application data is
not represented by Docker's volume summary and must never be inferred to be
unused from that output.

## Live Runtime Inventory

### H3: retain the core boundaries

| Runtime | Decision | Reason / exit condition |
| --- | --- | --- |
| `caddy`, `cloudflared` | Keep | Edge and authenticated ingress have distinct responsibilities. |
| `governor-api` | Keep | Synchronous PWA/API boundary and deterministic domain authority. |
| `kaos-governor-worker` | Keep | Continuous mail, fax, notification, digest, and recurring-task lifecycles are isolated from web requests. Do not merge into the API merely to reduce one container. |
| `governor-postgres` | Keep | Authoritative Governor workflow and audit state. |
| `calendar-adapter`, `radicale` | Keep | Adapter semantics and CalDAV source of truth are separate concerns. |
| `memos`, `personal-memos-web`, `family-memos-web` | Keep for now | Memos is authoritative. The two tiny web wrappers have separate host/theme modes; merging them has little current payoff. Revisit only during a shared portal deployment change. |
| `family-portal`, `roun-web` | Keep | Current family surfaces; consolidate UI code internally rather than introducing another backend. |
| `sftpgo`, `vaultwarden` | Keep independently | Useful upstream services, not KaosGDD domain engines. Avoid coupling new Governor workflows to them without a concrete need. |
| `n8n`, `n8n-postgres` | Time-boxed keep | One active weekly source monitor is not enough by itself to justify a permanent automation stack. Keep while evaluating two additional valuable workflows; otherwise retire both and return the monitor to a simpler native schedule. |
| `kaos-governor-tools` | Keep | Transport-neutral authenticated tool boundary for H4, PWA status, scoped Shortcuts, and imaging second-look. It owns port 8098 independently of Discord. |
| `kaos-governor-discord` | Transitional | Direct Discord feature schedulers and its embedded tools server are disabled. It now owns only the remaining Discord transport/compatibility surface and can enter an observation-before-retirement phase. |
| stopped `kaosgovernor-legacy-api` and `kaosgovernor-legacy-database` | Retirement candidate | Both are already stopped. Remove only after final rollback/data inspection and explicit approval. |

### H4: preserve OpenAI access, remove transport coupling deliberately

| Runtime | Decision | Reason / exit condition |
| --- | --- | --- |
| `openclaw-gateway.service` | Keep | Current OpenAI OAuth/model gateway used by KaosBrain capabilities. |
| `kaosai-openclaw-reauth-agent.service` | Keep until replaced | Maintains the current OAuth recovery path. Rename legacy `kaosai` paths during a planned deployment migration, not in place. |
| `kaosbrain.service` / `kaos-brain` | Transitional | It is still explicitly a Discord service and also carries Brain/Governor tool behavior. Inventory the PWA AI Tasks, document-tagging, calendar parsing, imaging, and tool call graph before splitting or retiring it. |
| `ollama.service` and local models | Measure | No model was loaded at the snapshot, while OpenAI/OpenClaw and OpenAI-backed imaging were enabled. Confirm actual fallback use over an observation period before disabling the service or removing approximately 21 GB of model files. |
| Mac mini runtime | Do not add in parallel | Add it only for a concrete macOS-only capability, or as a tested replacement for H4. Do not create a permanent second general Brain stack merely because the hardware is available. |

### Clinic: treat as an appliance

Keep the PACS, Paperless, HylaFAX bridge/connector, Stirling-PDF, and RustDesk
stacks outside application consolidation. They own specialized data or local
hardware paths and should change only through their own recovery-tested plans.

Keep `kaos-hylafax-backup.timer` and `kaos-faxmail-retention.timer` in systemd.
They are privileged, host-local work and do not belong in n8n. The inactive
`kaos-tailscale-container-recovery.service` is a normal oneshot helper and is
not evidence of failure.

`kaostelegram-control.service` is enabled and active. It is a root-owned,
hardened Unix-socket service-control helper rather than the Telegram chat bot
itself. No current repository caller or connected socket client was found in
the snapshot; only the helper was listening. Verify the remaining clinic
deployment dependency, then disable it for an observation period and remove it
through a separate approved retirement if it remains unused.

`rhwp` remains undecided. Retire it only after confirming that the HIRA HWPX
attachment workflow and all remaining manual conversions are covered by the
chosen replacement.

## Schedule and Worker Ownership

The desired single schedule view applies to ordinary application clocks, not
to every loop and host timer.

| Job | Current owner | Target | Decision |
| --- | --- | --- | --- |
| AI source health monitor | n8n, Sunday 03:30 KST | n8n | Keep read-only; no allowlist writes or unchanged-state notifications. |
| Recurring task sync | Governor worker, 300-second check with once-per-KST-day state | n8n trigger -> Governor sync API | Best first existing schedule to shadow because Governor already owns idempotent execution. Never run both production triggers. |
| Daily digest | Governor worker, 30-second schedule check | n8n trigger -> Governor assembly/outbox | Second candidate after recurring tasks. Preserve the current non-Discord delivery policy. |
| Mail organizer time window | Governor worker, 60-second scheduler check | Decide after mail reliability work | n8n may eventually open/close the window, but IMAP state and user-confirmed actions stay in Governor. |
| Naver mail intake | Governor worker, 60 seconds | Governor worker | Continuous mailbox polling and deduplication; do not recreate it as many n8n executions now. |
| Fax lifecycle | Governor worker, 20 seconds; clinic bridge/connector | Native workers | Local transport, files, acknowledgement, and final-state dedupe justify continuous workers. |
| Pushover outbox | Governor worker, 5 seconds | Governor worker | Durable queue consumer, not a calendar schedule. |
| Task due notifications | Governor/native calendar clients | Native authoritative clients | Avoid duplicate n8n reminders. |
| H3/H4/clinic OS maintenance | systemd | systemd / KaosSystemOperator | Privileged host boundary. |
| Full-host unresponsive detection | Not safely owned by H3 itself | External monitor on another host/provider | An H3-local n8n workflow cannot report that H3 is down. Notify only on a meaningful transition. |

For each schedule migration, record the existing trigger, executor, state
owner, idempotency key, timeout, retry behavior, notification behavior, and
rollback flag. Run a read-only or non-writing shadow first. Disable the native
trigger before enabling the n8n production trigger.

## Consolidation Work Queue

### Phase 1: remove known dead weight

1. Inspect the stopped legacy Governor database volume and rollback notes.
2. With explicit approval, remove the two stopped legacy containers; retain
   only the backup artifacts required by the recovery plan.
3. Perform a separately approved Docker build-cache prune on H3. This recovers
   space but does not simplify runtime ownership.

### Phase 2: remove the hidden H3 Discord dependency

1. **Complete 2026-09-08:** move the complete port 8098 route surface from
   `integrations/discoord` into the standalone `kaos-governor-tools` runtime.
2. **Complete 2026-09-08:** point Governor's
   `SYSTEM_STATUS_TOOLS_BASE_URL` at `http://governor-tools:8098` while keeping
   H4's existing tailnet address stable. Authenticated H3 and H4 live reads
   passed after cutover.
3. **Complete 2026-09-09:** read-only production observation passed with
   Discord's embedded tools disabled. Standalone `kaos-governor-tools` was
   healthy with zero restarts; authenticated system, calendar, task, Memos,
   Paperless, tag-context, mail, and imaging-status reads passed. H4 made
   authenticated system, today, document, and task reads directly through
   port 8098, and its AI Task, document-tag, calendar-preview, and imaging
   handlers passed authenticated validation probes without model calls or
   writes. H4 doctor also passed; its checkout was behind only in paths that
   do not affect the H4 Brain deployment.
4. Disable the H3 Discord container for an observation window, then remove it
   and its credential only after history/rollback decisions are complete.
   Before a rollback restart, account for the retained 2026-09-07 through
   2026-09-09 pending Discord digest publications so they cannot be replayed.
   Discord-side digest publishing is already disabled; worker-owned Pushover,
   mail/fax polling, recurring tasks, and digest scheduling remain independent.

### Phase 3: retire Discord as a Brain transport

1. Give PWA AI Tasks and other approved Brain clients a narrow,
   transport-neutral Governor-to-OpenClaw path.
2. Keep OpenClaw OAuth and the reauth path; do not expose the owner Gateway
   token directly to n8n or browsers.
3. Export or deliberately abandon required Discord history.
4. Disable the H4 Discord service and observe the PWA/OpenClaw replacement
   before deleting bot credentials or state.

### Phase 4: test centralized application scheduling

1. Shadow recurring-task sync from n8n without writes.
2. Cut over with an explicit `native`/`n8n` owner switch and verify KST/day
   behavior.
3. Repeat for daily digest only if the first cutover reduces maintenance.
4. Reassess n8n after it has operated the weekly monitor plus at least two
   useful workflows. If it has not earned that role, retire n8n and its
   PostgreSQL instead of inventing workflows to justify it.

### Phase 5: audit optional runtimes

1. Record actual Ollama requests/model use for an observation period; retain a
   small explicit fallback or remove unused models/service.
2. Verify and retire the clinic Telegram control helper if it has no caller.
3. Decide RHWP from the real HIRA attachment workflow.
4. Revisit duplicate theme/web wrappers only during related portal work; their
   current cost is too small to justify an independent rewrite.

## Change Admission Check

Before starting another KaosGDD feature, answer these questions:

- Does an existing PWA page, Governor domain, n8n workflow, or upstream service
  already cover most of it?
- Can it be a UI addition or a rule in an existing module rather than a new
  service?
- What existing component or manual workflow will it replace?
- Who owns its state, schedule, writes, retries, alerts, and recovery?
- Will it still be useful without an AI model or chat transport?
- If it adds a permanent runtime, does its repeated value justify backup,
  upgrades, monitoring, credentials, and failure handling?

If the answers are unclear, keep the idea in plans and do not implement it yet.
This is the default response to overlapping or low-value expansion, even when
the feature is technically possible.

## Immediate Recommendation

The transport-neutral H3 port 8098 Governor tools replacement is now live; do
not add a second tool boundary. Observe it before disabling the remaining H3
Discord transport. The first n8n migration should follow only after that, with
recurring-task sync as a one-owner, shadow-tested cutover.
