# KaosBrain deployment

KaosBrain runs on the H4 Ultra as the personal language interface for KaosGDD.
It talks directly to Discord and local Ollama. Authoritative state changes
remain behind KaosGovernor APIs.

OpenClaw/KaosAI planning is optional and disabled by default. Enable it only
after the local gateway and auth token are verified.

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

Create the secret file without printing it:

```bash
read -rsp "KaosBrain Discord bot token: " TOKEN; echo
printf '%s' "$TOKEN" > /srv/kaos/secrets/kaosbrain_discord_bot_token
unset TOKEN
chmod 0640 /srv/kaos/secrets/kaosbrain_discord_bot_token
```

Edit `/srv/kaos/brain/kaosbrain.env`, then test and start:

```bash
./deploy/kaosbrain/kaosbrain test
./deploy/kaosbrain/kaosbrain up
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
