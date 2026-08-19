# KaosBrain deployment

KaosBrain runs on the H4 Ultra as the personal language interface for KaosGDD.
It talks directly to Discord and local Ollama. Authoritative state changes
remain behind KaosGovernor APIs.

OpenClaw/KaosAI planning is optional and disabled by default. Enable it only
after the local gateway and auth token are verified.

The normal production shape is:

- KaosBrain Discord adapter and guard are always on.
- Local Ollama handles normal chat and deterministic intent help.
- KaosGovernor tool access is enabled after the H3 Governor tool API is
  reachable over Tailscale.
- KaosAI/OpenClaw remains disabled unless deliberately testing planner mode.

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
KAOSBRAIN_IMAGING_API_TOKEN_FILE=/run/secrets/governor_api_token
GOVERNOR_API_TOKEN_FILE=/run/secrets/governor_api_token
```

Leave `KAOSAI_API_TOKEN_FILE` unset or pointed at a missing placeholder while
`KAOSAI_ENABLED=false`; the deploy preflight only requires it when KaosAI is
enabled.

Use `KAOSAI_DRY_RUN_ENABLED=true` only with `KAOSAI_ENABLED=true`. In dry-run
mode, ordinary Brain chat renders the guarded KaosAI plan preview and skips all
Governor calls, confirmations, and writes.

Use the deploy helper to switch KaosAI modes without hand-editing the env file:

```bash
./deploy/kaosbrain/kaosbrain kaosai-mode disabled
./deploy/kaosbrain/kaosbrain kaosai-mode diagnostic
./deploy/kaosbrain/kaosbrain kaosai-mode dry-run
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
