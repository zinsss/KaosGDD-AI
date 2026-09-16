# KaosBrain deployment

KaosBrain runs on the H4 Ultra as a headless internal AI service for KaosGDD.
It serves health, preview, AI Task, imaging, and reauthorization HTTP routes;
it does not connect to Discord. Authoritative state changes remain behind
KaosGovernor APIs.

KaosBrain-OpenAI planning is optional and disabled by default. It is the
OpenClaw/ChatGPT Pro provider formerly called KaosAI. Enable it only after the
local gateway and auth token are verified.

The production shape is:

- KaosBrain's internal HTTP API and guard are always on.
- Local Ollama remains available for the configured local model paths.
- KaosGovernor tool access is enabled after the H3 Governor tool API is
  reachable over Tailscale.
- KaosBrain-OpenAI/OpenClaw remains disabled unless deliberately testing
  planner mode.

## Host prerequisites

- Debian 13 or Ubuntu 24.04 LTS
- Docker Engine
- Ollama reachable on `127.0.0.1:11434`
- Tailscale joined to the Kaos tailnet

## Install

From a fresh clone:

```bash
cd /srv/projects/KaosGDD-AI
./deploy/kaosbrain/kaosbrain setup
```

Fresh installs use the canonical KaosGDD layout:

```text
/srv/kaosgdd/kaosbrain/kaosbrain.env
```

Existing hosts with `/srv/kaos/brain/kaosbrain.env` keep using that legacy path
until a deliberate host path migration is performed.

If Governor tools or protected Brain routes are enabled, install the shared Governor API token as a
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
KAOSBRAIN_GOVERNOR_TOOLS_ENABLED=true
KAOSBRAIN_GOVERNOR_TOOLS_BASE_URL=http://<kaosgovernor-tailscale-ip>:8098
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

Port 8098 is the transport-neutral Governor tools service. The retired H3
Discord health route on port 8097 is not part of the headless deployment.

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

For general AI Tasks with broad web search, Governor can call:

```text
AI_TASKS_WEB_BRAIN_URL=http://<kaosbrain-tailscale-ip>:8099/internal/ai-tasks/web/preview
KAOSBRAIN_OPENAI_API_KEY_FILE=/run/secrets/openai_api_key
KAOSBRAIN_WEB_TASK_MODEL=gpt-5.6
```

If `AI_TASKS_WEB_BRAIN_URL` is blank and `AI_TASKS_BRAIN_URL` points at the
official-doc memo route above, Governor derives `/internal/ai-tasks/web/preview`
automatically. Web AI Tasks are read-only: KaosBrain returns an archived result
with sources, and the PWA offers optional copy/save-to-Memos actions only after
the preview exists. If `KAOSBRAIN_OPENAI_API_KEY_FILE` is unset, this route
falls back to KaosBrain-OpenAI through OpenClaw/OAuth, provided OpenClaw has web
search enabled:

```json
{
  "tools": {
    "web": {
      "search": {
        "enabled": true,
        "provider": "codex",
        "openaiCodex": {
          "enabled": true,
          "mode": "live"
        }
      },
      "fetch": {
        "enabled": true
      }
    }
  }
}
```

For the default official-health web-search pipeline, Governor derives and calls
two additional KaosBrain-OpenAI/OpenClaw endpoints from the same base URL:

```text
/internal/ai-tasks/official-web/plan
/internal/ai-tasks/official-web/summarize
```

`plan` turns the Korean prompt into a structured search job. Governor then
searches/fetches only its allowlisted Korean official/public health domains.
`summarize` receives only those fetched source excerpts and returns the
read-only AI Task result. This path uses the existing
`KAOSBRAIN_AI_TASK_API_TOKEN_FILE` shared token and does not require the
`KAOSBRAIN_OPENAI_API_KEY_FILE` Responses/web-search route.

Enable or disable the provider in the host-managed env file, then run
`kaosbrain up`:

```text
KAOSAI_ENABLED=true
KAOSAI_PROVIDER=openclaw
KAOSAI_BASE_URL=http://127.0.0.1:18789
KAOSAI_API_TOKEN_FILE=/run/secrets/openclaw_gateway_token
```

There are no chat, diagnostic, or dry-run transport modes in the headless
runtime. Protected HTTP endpoints call the configured provider directly.

When the OpenClaw ChatGPT/OpenAI OAuth profile expires, renew it from the H4
host checkout with one command:

```bash
./deploy/kaosbrain/kaosbrain openclaw-reauth
```

The helper loads the KaosGDD OpenClaw state path, switches to the required Node
runtime through `nvm` when needed, and starts OpenAI's device-pairing flow. Open
the displayed URL on any device and enter the displayed one-time code; no
localhost callback needs to be copied back to H4. After authorization, the
helper restarts `openclaw-gateway.service` and prints the non-secret auth
profile status.

For PWA-driven renewal, install the H4-local reauth agent. It is a separate
loopback-only service with a bearer token, so the Brain container does not get
host shell access:

```bash
./deploy/kaosbrain/kaosbrain openclaw-reauth-agent-setup
./deploy/kaosbrain/kaosbrain openclaw-reauth-agent-up
```

The agent exposes only:

```text
POST /reauth/openai/start
POST /reauth/openai/callback  # legacy compatibility; rejected during device pairing
GET  /reauth/openai/status
```

Authenticated `start` and `status` responses return `verificationUrl` and the
short-lived `userCode` while pairing is pending. The unauthenticated health
response contains only service health, and command output is redacted before it
is returned. Device pairing completes asynchronously, so clients should poll
`status` until it reports `succeeded` or `failed`.

The setup command creates:

```text
/srv/kaosgdd/kaosai/openclaw-reauth-agent.env
/srv/kaosgdd/secrets/kaosai_reauth_agent_token
~/.config/systemd/user/kaosai-openclaw-reauth-agent.service
```

After the first install, update Brain from the host checkout with:

```bash
cd /srv/projects/KaosGDD-AI
./deploy/kaosbrain/kaosbrain deploy
```

The first `up` after Discord retirement removes obsolete Discord/chat settings
and the old port-8097 Governor health variable from the env file. Before doing
so it preserves permission-aware rollback artifacts at:

```text
<kaosbrain.env>.pre-headless-discord-retirement
<kaosbrain.env>.unit.pre-headless-discord-retirement
kaos-brain:pre-headless-discord-retirement  # Docker image tag
```

If only the old `KAOSBRAIN_GOVERNOR_HEALTH_URL` was configured, the migration
derives `KAOSBRAIN_GOVERNOR_TOOLS_BASE_URL` on port 8098 before removing it.
The helper never overwrites these artifacts. If a rollback image tag already
points elsewhere without a complete matching env/unit backup, cutover fails
closed. Keep all three through the observation window. To roll back after a
successful cutover, restore the previous application revision, retag
`kaos-brain:pre-headless-discord-retirement` as the configured live image,
restore the env and unit with `cp -p`, restore the quarantined token described
below, run `systemctl daemon-reload`, and restart the old service. Remove the
rollback artifacts only after the headless service, PWA AI Tasks,
calendar/document previews, imaging, and reauthorization have all been
observed working.

`up` performs the risky work as a staged cutover. It first applies the env
migration to a temporary copy, runs preflight against that copy, and builds a
separate candidate image tag. None of those steps changes the live env, unit,
image tag, secrets, or running service. It then snapshots the current env,
systemd unit, image ID, and running state before installing the candidate.
After restart, smoke requires the full headless `/health` payload and an
authenticated `GET /internal/openclaw-auth/status`; HTTP 200 is healthy and
HTTP 503 is valid only for a deliberately disabled reauth integration. HTTP
401 or any other status fails the cutover. The bearer value is passed to curl
over stdin and is never printed.

If migration, unit installation, quarantine, restart, health validation, or
the authenticated route fails, `up` stops the candidate and automatically
restores the old env, unit, image tag, quarantined tokens, and prior running
state. If automatic rollback itself cannot finish, the helper leaves its
mode-`0700` recovery snapshot in place and prints only that directory path.

After the new image builds successfully, `up` also moves the known KaosBrain
Discord token files out of mounted secret directories. This includes the exact
canonical and legacy locations plus custom paths selected by the historical
`KAOSBRAIN_TOKEN_FILE`, `KAOSBRAIN_SECRETS_DIR`, or
`DISCORD_BOT_TOKEN_FILE=/run/secrets/...` settings. Contents are never read or
printed; modes and ownership are preserved under a directory restricted to
mode `0700`:

```text
/srv/kaosgdd/kaosbrain/retired-secrets/canonical-kaosbrain_discord_bot_token
/srv/kaosgdd/kaosbrain/retired-secrets/legacy-kaosbrain_discord_bot_token
```

Custom copies use distinct `configured-host-`, `configured-runtime-`, or
`effective-` filenames in the same directory. The migration is idempotent and
refuses symlinks, non-regular files, destination collisions, and any path that
is still configured as a headless/Governor credential. For an old-code
rollback after a successful observation window, stop the service and move the
appropriate quarantined file back to its original location before restoring
the old env and service revision.

When the reauth agent package or unit changes, reinstall and restart that
separate user service explicitly:

```bash
./deploy/kaosbrain/kaosbrain openclaw-reauth-agent-setup
./deploy/kaosbrain/kaosbrain openclaw-reauth-agent-up
```

## Verify

```bash
systemctl status kaosbrain.service --no-pager
docker ps --filter name=kaos-brain
curl -fsS http://127.0.0.1:11434/api/tags >/dev/null
curl -fsS http://<kaosbrain-tailscale-ip>:8099/health
./deploy/kaosbrain/kaosbrain status
./deploy/kaosbrain/kaosbrain doctor
```

The health response must report `status=ok`, `runtime=headless`, and
`httpReady=true`. `doctor` also checks the Governor tools `/health` endpoint on
port 8098 and never probes a Discord service.

## Rollback

```bash
sudo systemctl disable --now kaosbrain.service
docker rm -f kaos-brain
```
