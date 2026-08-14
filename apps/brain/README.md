# KaosBrain

KaosBrain is the lightweight personal language interface for KaosGDD.

It intentionally bypasses OpenClaw. The service talks to Discord directly, calls
Ollama directly, and leaves authoritative state changes to KaosGovernor.

## Authority Boundary

- KaosBrain may answer conversationally.
- KaosBrain may classify intent and draft text.
- KaosBrain must not directly own calendars, tasks, memos, documents, mail, fax,
  infrastructure, or databases.
- Durable reads and writes should go through narrow KaosGovernor APIs.

## Current Slice

- Discord message intake for one configured `#brain` channel.
- Allowed-user and guild checks.
- Direct Ollama `/api/chat` calls.
- Fast chat model and explicit deep model routing.
- `deep:`, `think:`, `깊게:`, and `생각:` prefixes route to the deep model.

## Required Environment

```sh
DISCORD_BOT_TOKEN_FILE=/run/secrets/discord_bot_token
DISCORD_GUILD_ID=1536016949127942164
DISCORD_ALLOWED_USER_IDS=...
DISCORD_BRAIN_CHANNEL_ID=1536983928337076224
OLLAMA_BASE_URL=http://127.0.0.1:11434
KAOSBRAIN_CHAT_MODEL=gemma3:4b
KAOSBRAIN_DEEP_MODEL=qwen3:8b
```

Use the same Discord bot token exclusivity rule as every Discord service: never
run two processes with the same token at the same time.

## Test

```sh
PYTHONPATH=apps/brain/src python3 -m unittest discover -s apps/brain/tests
docker build --target test --tag kaos-brain:test --file apps/brain/Dockerfile .
docker run --rm kaos-brain:test
```
