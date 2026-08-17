# KaosBrain

KaosBrain is the lightweight personal language interface and guard for
KaosGDD.

The current production service talks to Discord directly, calls Ollama directly
for conversational fallback, and leaves authoritative state changes to
KaosGovernor. The next architecture introduces KaosAI as a planner slot:

```text
KaosAI      = OpenClaw/ChatGPT Pro planner
KaosBrain   = adapter and deterministic guard
KaosGovernor = authoritative tools, confirmations, and audit
```

See [KaosAI, KaosBrain, and KaosGovernor](../../docs/architecture/kaosai-brain-governor.md).

## Authority Boundary

- KaosBrain may answer conversationally.
- KaosBrain may classify intent, adapt KaosAI plans, and draft text.
- KaosBrain must not directly own calendars, tasks, memos, documents, mail, fax,
  infrastructure, or databases.
- Durable reads and writes should go through narrow KaosGovernor APIs.
- KaosAI must not receive Governor credentials or call Governor tools directly.

## Current Slice

- Discord message intake for one configured `#brain` channel.
- Allowed-user and guild checks.
- Direct Ollama `/api/chat` calls.
- Fast chat model and automatic deep model routing.
- `deep:`, `think:`, `깊게:`, and `생각:` prefixes route to the deep model.
- KaosAI plan contract and deterministic Brain Guard skeleton.
- Read-only KaosGovernor tool calls for today, active tasks, Memos search, and
  Paperless document search.
- Confirmed KaosGovernor task due-date updates from narrow natural-language
  commands.

Task edits do not run directly. KaosBrain asks KaosGovernor to create a
confirmation, shows Confirm/Cancel buttons in Discord, and only the Confirm
button applies the Radicale task update through Governor.

## Required Environment

```sh
DISCORD_BOT_TOKEN_FILE=/run/secrets/kaosbrain_discord_bot_token
DISCORD_GUILD_ID=1536016949127942164
DISCORD_ALLOWED_USER_IDS=...
DISCORD_BRAIN_CHANNEL_ID=1536983928337076224
OLLAMA_BASE_URL=http://127.0.0.1:11434
KAOSBRAIN_CHAT_MODEL=gemma3:4b
KAOSBRAIN_DEEP_MODEL=qwen3:8b
KAOSBRAIN_AUTO_ROUTE_ENABLED=true
KAOSAI_ENABLED=false
KAOSAI_PROVIDER=disabled
KAOSAI_BASE_URL=
KAOSAI_MODEL=default
KAOSAI_API_TOKEN_FILE=/run/secrets/openclaw_gateway_token
KAOSAI_CHAT_ENABLED=false
KAOSBRAIN_GOVERNOR_TOOLS_ENABLED=true
KAOSBRAIN_GOVERNOR_TOOLS_BASE_URL=http://<kaosgovernor-tailscale-ip>:8098
KAOSBRAIN_GOVERNOR_TOOLS_PROFILE=main
KAOSBRAIN_SUPPLIES_COLLECTION_ID=supplies:<radicale-vtodo-collection-id>
KAOSBRAIN_MEMOS_PUBLIC_URL=
KAOSBRAIN_HEALTH_ENABLED=true
KAOSBRAIN_HEALTH_HOST=<kaosbrain-tailscale-ip>
KAOSBRAIN_HEALTH_PORT=8099
GOVERNOR_API_TOKEN_FILE=/run/secrets/governor_api_token
```

Bind the health endpoint only to loopback or the KaosBrain Tailscale IP. It is
for KaosGovernor system status probes, not public access.

Supported write grammar in this slice:

```text
영이 큐시미아 다음주 월요일까지로 편집
엄마 전화 기한 내일로 변경
보험 서류 마감일을 2026-08-20로 수정
```

The default due time is `10:00`.

KaosAI is a guarded planner dependency only when explicitly enabled. The
OpenClaw planner client uses the local OpenClaw WebSocket gateway and expects
strict JSON plans only; KaosBrain Guard adapts and validates those plans before
Governor sees them. `KAOSAI_CHAT_ENABLED=false` keeps normal Brain chat on the
local deterministic path while still allowing explicit `ai:` diagnostics.

KaosAI diagnostics are available in the configured Brain channel and never
execute or propose writes:

```text
ai:ping
ai:plan 내일까지 엄마한테 전화해야돼
```

Use the same Discord bot token exclusivity rule as every Discord service: never
run two processes with the same token at the same time.

## Test

```sh
PYTHONPATH=apps/brain/src python3 -m unittest discover -s apps/brain/tests
docker build --target test --tag kaos-brain:test --file apps/brain/Dockerfile .
docker run --rm kaos-brain:test
```
