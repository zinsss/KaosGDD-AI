# KaosBrain-OpenAI Legacy Cleanup Plan

Decision date: 2026-09-03

Status: planned only. Do not execute this cleanup during unrelated feature work.

## Purpose

The visible architecture now uses these names:

- `KaosBrain`: top AI manager/orchestrator for KaosGDD.
- `KaosBrain-OpenAI`: OpenClaw/ChatGPT Pro provider implementation formerly
  called `KaosAI`.
- `KaosGovernor`: deterministic authority for validation, confirmation, audit,
  and execution routing.

Commit `9494d40` changed user-facing labels, health/status output, and docs
while preserving legacy internals. The remaining cleanup is intentionally
separate because it touches env names, host paths, service units, tests, and
operator runbooks.

## Current Compatibility State

The following are still legacy-compatible and should remain working until this
plan is deliberately executed:

- Python module/class names:
  - `apps/brain/src/kaos_brain/kaos_ai.py`
  - `KaosAIError`
  - `KaosAIPlanner`
  - `KaosAIConfig`
  - `OpenClawKaosAIPlanner`
- environment variables:
  - `KAOSAI_ENABLED`
  - `KAOSAI_PROVIDER`
  - `KAOSAI_BASE_URL`
  - `KAOSAI_MODEL`
  - `KAOSAI_API_TOKEN_FILE`
  - `KAOSAI_CHAT_ENABLED`
  - `KAOSAI_DRY_RUN_ENABLED`
  - `KAOSAI_REAUTH_*`
  - `KAOSAI_OPENCLAW_*`
- host paths:
  - `/srv/kaosgdd/kaosai`
  - `/srv/kaosgdd/secrets/kaosai_reauth_agent_token`
- service names:
  - `kaosai-openclaw-reauth-agent.service`
- command aliases:
  - `./deploy/kaosbrain/kaosbrain kaosai-mode ...`
- health compatibility:
  - `kaosAI.mode` remains beside `kaosBrainOpenAI.mode`
- internal error codes:
  - `kaosai_*`
  - `kaosai_gateway_*`

## Target End State

After cleanup, new code and docs should use:

- module/provider naming around `kaosbrain_openai`
- `KaosBrainOpenAI*` class names
- `KAOSBRAIN_OPENAI_*` environment variables
- `/srv/kaosgdd/kaosbrain/openai` or another explicitly chosen Brain-owned
  provider path
- `kaosbrain-openai-reauth-agent.service`
- `brain-openai-mode` as the only documented command
- `kaosBrainOpenAI.mode` as the only non-legacy health key

Legacy names should be removed only after at least one deployed cycle proves
the aliases work.

## Phase 0 — Inventory and Freeze

Goal: prove the current legacy surface before changing it.

Affected files:

- `apps/brain/src/kaos_brain/*`
- `apps/brain/tests/*kaosai*`
- `deploy/kaosbrain/*`
- `docs/architecture/*`
- `docs/migration/*`
- `docs/operations/*`
- `integrations/discoord/src/kaosdiscoord/*`
- `integrations/discoord/tests/*`

Actions:

1. Run `rg -n "KaosAI|kaosAI|kaosai|KAOSAI"` and classify each match as:
   internal symbol, env var, host path, service unit, health key, error code,
   test fixture, or historical note.
2. Save the inventory in this document before starting Phase 1.
3. Confirm H4 doctor and H3 service-status smoke pass on the current commit.

Tests:

- full Brain Docker test target
- full Discoord/Governor Docker test target
- H4 `kaosbrain doctor`
- H3 Governor/Discoord smoke

Rollback:

- no behavior change in this phase.

## Phase 1 — Python Provider Aliases

Goal: introduce new code names without breaking imports.

Actions:

1. Add a new provider module, likely:
   - `apps/brain/src/kaos_brain/kaosbrain_openai.py`
2. Move or wrap implementation under new names:
   - `KaosBrainOpenAIError`
   - `KaosBrainOpenAIPlanner`
   - `KaosBrainOpenAIConfig`
   - `OpenClawKaosBrainOpenAIPlanner`
3. Keep `kaos_ai.py` as a compatibility shim that imports/re-exports the new
   symbols.
4. Update production imports to use the new module.
5. Keep old test module names temporarily if that reduces churn, but update
   assertions and fixture class names where practical.

Behavior changes:

- none intended.

Risk:

- low to medium. Import mistakes can break Brain startup.

Tests:

- `docker build --target test --tag kaosgdd-ai-brain:rename-phase1 --file apps/brain/Dockerfile .`
- `docker run --rm kaosgdd-ai-brain:rename-phase1`
- focused imports test from a mounted working tree.

Rollback:

- revert the alias/module commit. No host state migration occurs.

## Phase 2 — Environment Variable Aliases

Goal: allow new env names while old env names still work.

New preferred env names:

```text
KAOSBRAIN_OPENAI_ENABLED
KAOSBRAIN_OPENAI_PROVIDER
KAOSBRAIN_OPENAI_BASE_URL
KAOSBRAIN_OPENAI_MODEL
KAOSBRAIN_OPENAI_API_TOKEN_FILE
KAOSBRAIN_OPENAI_CHAT_ENABLED
KAOSBRAIN_OPENAI_DRY_RUN_ENABLED
KAOSBRAIN_OPENAI_REAUTH_ENABLED
KAOSBRAIN_OPENAI_REAUTH_BASE_URL
KAOSBRAIN_OPENAI_REAUTH_TOKEN_FILE
KAOSBRAIN_OPENAI_OPENCLAW_STATE_DIR
KAOSBRAIN_OPENAI_OPENCLAW_CONFIG_PATH
KAOSBRAIN_OPENAI_OPENCLAW_GATEWAY_SERVICE
```

Actions:

1. Update `Settings.from_env` to read new names first, then legacy `KAOSAI_*`.
2. Update `deploy/kaosbrain/kaosbrain` to write both new and legacy names
   during the transition, or to write new names and preserve legacy fallback.
3. Update env examples and docs.
4. Add tests proving new-only, old-only, and mixed env configurations.

Behavior changes:

- none intended.

Risk:

- medium. Env precedence mistakes can silently select the wrong provider mode.

Tests:

- Brain config tests for new-only, old-only, and conflict cases.
- H4 preflight with current legacy env.
- H4 preflight with a copied test env using new names.

Rollback:

- revert Phase 2 commit; host env remains legacy-compatible.

## Phase 3 — Health and Status Contract Migration

Goal: move consumers to the new health key.

Actions:

1. Keep Brain emitting both:
   - `kaosBrainOpenAI.mode`
   - `kaosAI.mode`
2. Update all consumers to prefer `kaosBrainOpenAI.mode`.
3. Add tests that old payloads still render correctly during the transition.
4. After one stable deployed cycle, schedule removal of `kaosAI.mode`.

Behavior changes:

- none during compatibility window.

Risk:

- low. Existing commit `9494d40` already starts this.

Tests:

- `brain_health_detail` with new-only and old-only payloads.
- H3 service-status smoke shows `KaosBrain-OpenAI`.

Rollback:

- keep both keys longer.

## Phase 4 — Host Path Migration

Goal: move provider runtime state from the legacy `kaosai` path into a
Brain-owned provider path.

Candidate target:

```text
/srv/kaosgdd/kaosbrain/openai/
  openclaw/
  openclaw-reauth-agent.env
  openclaw-reauth-agent-venv/
```

Actions:

1. Stop only the affected services:
   - `kaosbrain.service`
   - `openclaw-gateway.service`
   - legacy reauth agent
2. Copy state with ownership and modes preserved.
3. Update H4 env paths to new `KAOSBRAIN_OPENAI_*` names.
4. Reinstall or update systemd units.
5. Start services.
6. Verify OpenClaw auth profile status without printing secrets.
7. Run H4 doctor and a Brain chat smoke.
8. Keep the old path as rollback for at least one stable cycle.

Behavior changes:

- runtime state path changes only.

Risk:

- high. A bad path migration can break OpenClaw auth, Brain startup, or reauth.

Tests:

- H4 preflight before stop.
- H4 doctor after start.
- OpenClaw gateway health/status.
- `brain-openai-mode diagnostic` dry test against copied env if possible.

Rollback:

- stop services, point env/unit paths back to `/srv/kaosgdd/kaosai`, restart,
  and run doctor.

## Phase 5 — Systemd Service Rename

Goal: replace legacy service unit names.

Target:

- from `kaosai-openclaw-reauth-agent.service`
- to `kaosbrain-openai-reauth-agent.service`

Actions:

1. Install the new unit.
2. Enable/start the new unit.
3. Confirm the old unit is stopped and disabled.
4. Update maintenance scripts, status scripts, and docs.
5. Keep a one-command rollback path to re-enable the old unit.

Behavior changes:

- service name changes; function remains identical.

Risk:

- medium. User-level systemd units are easy to orphan if both run.

Tests:

- `systemctl --user status kaosbrain-openai-reauth-agent.service`
- reauth start/status smoke
- H4 doctor

Rollback:

- stop/disable new unit, re-enable old unit, restore env path if needed.

## Phase 6 — Internal Error Code Migration

Goal: stop producing new `kaosai_*` error codes.

Actions:

1. Introduce new internal codes:
   - `kaosbrain_openai_disabled`
   - `kaosbrain_openai_gateway_agent_failed`
   - `kaosbrain_openai_gateway_connect_failed`
   - etc.
2. Keep a compatibility mapper for logs/tests that still see old provider
   gateway codes.
3. Update tests and operator docs.

Behavior changes:

- operator/debug strings change.

Risk:

- medium. Error codes may be used in auth-failure detection or logs.

Tests:

- auth-expired detection still triggers renewal UI.
- second-look provider failure still returns clear 502 JSON.
- no user-facing regression in Discord or PWA status.

Rollback:

- keep old codes until all consumers are confirmed.

## Phase 7 — Remove Legacy Aliases

Goal: remove old compatibility only after deployed evidence.

Prerequisites:

- H4 has run at least one stable cycle with new env names.
- H3 service status sees only `kaosBrainOpenAI.mode`.
- No docs, runbooks, or scripts require `kaosai-mode`.
- No live systemd unit uses `kaosai-openclaw-reauth-agent.service`.
- Backups or path rollback are retained.

Actions:

1. Remove `kaos_ai.py` shim if all imports are migrated.
2. Remove `KAOSAI_*` fallback reads.
3. Remove `kaosai-mode` command alias.
4. Remove `kaosAI.mode` health key.
5. Remove old host path after backup/retention decision.

Risk:

- medium to high. This is where backward compatibility is intentionally
  removed.

Tests:

- full Brain Docker test target
- full Discoord/Governor Docker test target
- H4 deploy + doctor
- H3 deploy + service-status smoke
- manual Discord `#brain` smoke

Rollback:

- revert the alias-removal commit and restore previous host env/path from
  retained backup.

## Explicit Non-Goals

- Do not change provider choice, model choice, or OpenAI/OpenClaw auth method.
- Do not give Brain direct Governor/database/backend credentials.
- Do not move H3 Governor responsibilities into Brain.
- Do not rename KaosPACS-AIO or KaosAIO as part of this cleanup.
- Do not remove local Ollama fallback.
- Do not change Discord retirement scope.
- Do not perform host path or systemd migration during UI/PWA work.
- Do not delete legacy files until rollback evidence exists.

## Current Recommended Next Step

Do Phase 0 inventory next, then Phase 1 Python aliases. Do not start Phase 4
host paths until the new env aliases have already passed one deployed cycle.
