# KaosBrain

KaosBrain is the headless language and AI orchestration service for KaosGDD.
It exposes a narrow internal HTTP API on H4 for health checks, calendar and
document previews, AI Tasks, imaging second-look, and OpenClaw reauthorization.
It has no chat transport and never connects to Discord.

```text
KaosBrain        = headless AI manager/orchestrator for KaosGDD
KaosBrain-OpenAI = OpenClaw/ChatGPT Pro provider, formerly called KaosAI
KaosGovernor     = authoritative tools, confirmations, and audit
```

See [KaosBrain, KaosBrain-OpenAI, and KaosGovernor](../../docs/architecture/kaosai-brain-governor.md).
Runtime paths follow [Runtime Layout](../../docs/architecture/runtime-layout.md):
KaosBrain belongs under `/srv/kaosgdd/kaosbrain`. Current OpenClaw/OpenAI host
paths and environment variables may still use the legacy `kaosai` name until a
separate host-path migration is performed.

## Authority boundary

- KaosBrain may classify intent, adapt KaosBrain-OpenAI plans, and draft text.
- KaosBrain must not directly own calendars, tasks, memos, documents, mail,
  fax, infrastructure, or databases.
- Durable reads and writes go through narrow KaosGovernor APIs.
- KaosBrain-OpenAI must not receive Governor credentials or call Governor
  tools directly.

## HTTP surface

The headless API is always enabled. Bind it only to loopback or the H4
Tailscale IP; it is not a public route.

```text
GET  /health
POST /internal/openclaw-auth/start
GET  /internal/openclaw-auth/status
POST /internal/calendar/smart-events/preview
POST /internal/documents/tag-suggestions/preview
POST /internal/ai-tasks/official-doc-memo/preview
POST /internal/ai-tasks/web/preview
POST /internal/ai-tasks/official-web/plan
POST /internal/ai-tasks/official-web/summarize
POST /imaging/second-look
```

Every route except `/health` uses its configured bearer token. The health
payload reports `runtime=headless`, `httpReady=true`, model names, and the
KaosBrain-OpenAI mode without exposing credentials. The legacy `kaosAI.mode`
key remains present for older clients during the provider rename window.

## Environment

```sh
OLLAMA_BASE_URL=http://127.0.0.1:11434
KAOSBRAIN_CHAT_MODEL=gemma3:4b
KAOSBRAIN_DEEP_MODEL=qwen3:8b
KAOSBRAIN_HEALTH_HOST=<kaosbrain-tailscale-ip>
KAOSBRAIN_HEALTH_PORT=8099

KAOSBRAIN_GOVERNOR_TOOLS_ENABLED=true
KAOSBRAIN_GOVERNOR_TOOLS_BASE_URL=http://<kaosgovernor-tailscale-ip>:8098
KAOSBRAIN_GOVERNOR_TOOLS_PROFILE=main
GOVERNOR_API_TOKEN_FILE=/run/secrets/governor_api_token

KAOSBRAIN_CALENDAR_PREVIEW_API_TOKEN_FILE=/run/secrets/governor_api_token
KAOSBRAIN_DOCUMENT_TAG_API_TOKEN_FILE=/run/secrets/governor_api_token
KAOSBRAIN_AI_TASK_API_TOKEN_FILE=/run/secrets/governor_api_token
KAOSBRAIN_IMAGING_API_TOKEN_FILE=/run/secrets/governor_api_token
```

`KAOSBRAIN_GOVERNOR_TOOLS_BASE_URL` points to the transport-neutral Governor
tools service on port 8098. The H3 Discord health service on port 8097 is
retired and must not be used by Brain.

KaosBrain-OpenAI is optional. When enabled, its OpenClaw planner returns strict
JSON plans; Brain Guard validates those plans before Governor sees them.

## Test

```sh
PYTHONPATH=apps/brain/src python3 -m unittest discover -s apps/brain/tests
docker build --target test --tag kaos-brain:test --file apps/brain/Dockerfile .
docker run --rm kaos-brain:test
```
