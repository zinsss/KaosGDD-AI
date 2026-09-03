# KaosBrain deployment

KaosBrain runs on the H4 Ultra as the personal language interface for KaosGDD.
It talks directly to Discord and local Ollama. Authoritative state changes
remain behind KaosGovernor APIs.

KaosBrain-OpenAI planning is optional and disabled by default. It is the
OpenClaw/ChatGPT Pro provider formerly called KaosAI. Enable it only after the
local gateway and auth token are verified.

The normal production shape is:

- KaosBrain Discord adapter and guard are always on.
- Local Ollama handles normal chat and deterministic intent help.
- KaosGovernor tool access is enabled after the H3 Governor tool API is
  reachable over Tailscale.
- KaosBrain-OpenAI/OpenClaw remains disabled unless deliberately testing
  planner mode.

## Host prerequisites

- Debian 13 or Ubuntu 24.04 LTS
- Docker Engine
- Ollama reachable on `127.0.0.1:11434`
- Tailscale joined to the Kaos tailnet
- a separate Discord bot token from KaosGovernor

## Install

From a fresh clone:

```bash
cd /srv/projects/KaosGDD-AI
./deploy/kaosbrain/kaosbrain setup
```

Fresh installs use the canonical KaosGDD layout:

```text
/srv/kaosgdd/kaosbrain/kaosbrain.env
/srv/kaosgdd/secrets/kaosbrain_discord_bot_token
```

Existing hosts with `/srv/kaos/brain/kaosbrain.env` keep using that legacy path
until a deliberate host path migration is performed.

Create the secret file without printing it:

```bash
read -rsp "KaosBrain Discord bot token: " TOKEN; echo
printf '%s' "$TOKEN" > /srv/kaosgdd/secrets/kaosbrain_discord_bot_token
unset TOKEN
chmod 0640 /srv/kaosgdd/secrets/kaosbrain_discord_bot_token
```

If Governor tools are enabled, also install the shared Governor API token as a
file-backed secret. Do not print the token in shell history or logs:

```bash
install -m 0640 /path/to/governor_api_token /srv/kaosgdd/secrets/governor_api_token
```

Edit `/srv/kaosgdd/kaosbrain/kaosbrain.env`, then test and start:

```bash
./deploy/kaosbrain/kaosbrain test
./deploy/kaosbrain/kaosbrain up
```

For the current H4-to-H3 layout, the important environment values are:

```text
KAOSAI_ENABLED=false
KAOSAI_PROVIDER=disabled
KAOSAI_BASE_URL=
KAOSAI_CHAT_ENABLED=false
KAOSAI_DRY_RUN_ENABLED=false
KAOSBRAIN_GOVERNOR_TOOLS_ENABLED=true
KAOSBRAIN_GOVERNOR_TOOLS_BASE_URL=http://<kaosgovernor-tailscale-ip>:8098
KAOSBRAIN_GOVERNOR_HEALTH_URL=http://<kaosgovernor-tailscale-ip>:8097/health
KAOSBRAIN_GOVERNOR_TOOLS_PROFILE=main
KAOSBRAIN_IMAGING_ENABLED=false
KAOSBRAIN_IMAGING_PROVIDER=kaosai
KAOSBRAIN_IMAGING_API_TOKEN_FILE=/run/secrets/governor_api_token
KAOSBRAIN_CALENDAR_PREVIEW_API_TOKEN_FILE=/run/secrets/governor_api_token
KAOSBRAIN_DOCUMENT_TAG_API_TOKEN_FILE=/run/secrets/governor_api_token
GOVERNOR_API_TOKEN_FILE=/run/secrets/governor_api_token
```

Leave `KAOSAI_API_TOKEN_FILE` unset or pointed at a missing placeholder while
`KAOSAI_ENABLED=false`; the deploy preflight only requires it when
KaosBrain-OpenAI is enabled. The `KAOSAI_*` names are legacy environment names
kept for compatibility.

Use `KAOSAI_DRY_RUN_ENABLED=true` only with `KAOSAI_ENABLED=true`. In dry-run
mode, ordinary Brain chat renders the guarded KaosBrain-OpenAI plan preview and
skips all Governor calls, confirmations, and writes.

For KaosPACS-AIO second-look, AIO calls Governor on H3 and Governor forwards to
KaosBrain:

```text
IMAGING_SECOND_LOOK_URL=http://<kaosbrain-tailscale-ip>:8099/imaging/second-look
IMAGING_SECOND_LOOK_TOKEN_FILE=/run/secrets/governor_api_token
KAOSBRAIN_IMAGING_ENABLED=true
KAOSBRAIN_IMAGING_PROVIDER=kaosbrain-openai
```

The payload contains rendered previews only. KaosBrain/KaosBrain-OpenAI returns a
temporary second-look checklist, not a diagnosis or clinical report.

For Family smart calendar parsing, the Family PWA calls Calendar Adapter on H3,
and Calendar Adapter can forward preview-only text to KaosBrain:

```text
CALENDAR_SMART_EVENTS_AI_URL=http://<kaosbrain-tailscale-ip>:8099/internal/calendar/smart-events/preview
CALENDAR_SMART_EVENTS_AI_TOKEN=<same value as KAOSBRAIN_CALENDAR_PREVIEW_API_TOKEN>
KAOSBRAIN_CALENDAR_PREVIEW_API_TOKEN_FILE=/run/secrets/governor_api_token
```

The Brain route returns candidate events only. The PWA still requires
`확인 후 저장` before Calendar Adapter writes to Radicale.

For personal Paperless tag suggestions, Governor calls KaosBrain on H4:

```text
DOCUMENT_TAG_AI_URL=http://<kaosbrain-tailscale-ip>:8099/internal/documents/tag-suggestions/preview
KAOSBRAIN_DOCUMENT_TAG_API_TOKEN_FILE=/run/secrets/governor_api_token
```

The Brain route returns suggested existing tag names only. The PWA still
requires metadata `PREVIEW` and confirmed `APPLY` before Paperless is updated.

For AI Tasks such as official-source summaries into Memos, Governor calls
KaosBrain on H4:

```text
AI_TASKS_BRAIN_URL=http://<kaosbrain-tailscale-ip>:8099/internal/ai-tasks/official-doc-memo/preview
KAOSBRAIN_AI_TASK_API_TOKEN_FILE=/run/secrets/governor_api_token
```

The Brain route returns a memo draft only. The PWA still requires `SAVE MEMO`
before anything is written to Memos, then Governor marks the AI Task archived
record as applied.

For general AI Tasks with web search, Governor calls:

```text
AI_TASKS_WEB_BRAIN_URL=http://<kaosbrain-tailscale-ip>:8099/internal/ai-tasks/web/preview
KAOSBRAIN_OPENAI_API_KEY_FILE=/run/secrets/openai_api_key
KAOSBRAIN_WEB_TASK_MODEL=gpt-5.6
```

If `AI_TASKS_WEB_BRAIN_URL` is blank and `AI_TASKS_BRAIN_URL` points at the
official-doc memo route above, Governor derives `/internal/ai-tasks/web/preview`
automatically. Web AI Tasks are read-only: KaosBrain returns an archived result
with sources, and the PWA offers optional copy/save-to-Memos actions only after
the preview exists.

Use the deploy helper to switch KaosBrain-OpenAI modes without hand-editing the
env file:

```bash
./deploy/kaosbrain/kaosbrain brain-openai-mode disabled
./deploy/kaosbrain/kaosbrain brain-openai-mode diagnostic
./deploy/kaosbrain/kaosbrain brain-openai-mode dry-run
```

The helper validates with `preflight` and restores the previous env file if the
new mode is not deployable. Restart remains explicit with `kaosbrain up`.

When the OpenClaw ChatGPT/OpenAI OAuth profile expires, renew it from the H4
host checkout with one command:

```bash
./deploy/kaosbrain/kaosbrain openclaw-reauth
```

The helper loads the KaosGDD OpenClaw state path, switches to the required Node
runtime through `nvm` when needed, starts the OpenAI OAuth flow, accepts the
callback URL or authorization code, restarts `openclaw-gateway.service`, and
prints the non-secret auth profile status.

For Discord-driven renewal, install the H4-local reauth agent. It is a separate
loopback-only service with a bearer token, so the Brain container does not get
host shell access:

```bash
./deploy/kaosbrain/kaosbrain openclaw-reauth-agent-setup
./deploy/kaosbrain/kaosbrain openclaw-reauth-agent-up
```

The agent exposes only:

```text
POST /reauth/openai/start
POST /reauth/openai/callback
GET  /reauth/openai/status
```

The setup command creates:

```text
/srv/kaosgdd/kaosai/openclaw-reauth-agent.env
/srv/kaosgdd/secrets/kaosai_reauth_agent_token
~/.config/systemd/user/kaosai-openclaw-reauth-agent.service
```

After the first install, update from the host checkout with:

```bash
cd /srv/projects/KaosGDD-AI
./deploy/kaosbrain/kaosbrain deploy
```

## Verify

```bash
systemctl status kaosbrain.service --no-pager
docker ps --filter name=kaos-brain
curl -fsS http://127.0.0.1:11434/api/tags >/dev/null
./deploy/kaosbrain/kaosbrain status
./deploy/kaosbrain/kaosbrain doctor
```

Then smoke test in the configured Discord `#brain` channel:

```text
안녕
deep: 한국어로 짧게 대답해줘
```

## Rollback

```bash
sudo systemctl disable --now kaosbrain.service
docker rm -f kaos-brain
```
